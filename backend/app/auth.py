"""User accounts and sessions.

* Passwords are hashed with scrypt (random 16-byte salt); plaintext is never stored or logged.
* Sessions are random 32-byte tokens sent as an HttpOnly, SameSite=Lax cookie.
  Only a SHA-256 hash of the token is stored, so a database leak does not leak sessions.
* Failed logins are rate limited per email and per client address.
* Every API resource is scoped to its owner; experience memory is a per-user namespace.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuthSession, User, get_session, utcnow

COOKIE = "if_session"
SESSION_DAYS = 14
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
_fails: dict[str, deque] = defaultdict(deque)
MAX_FAILS, WINDOW_S = 5, 600


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def memory_namespace(user_id: str) -> str:
    return f"user:{user_id}"


def validate_credentials(email: str, password: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(password) < 8 or len(password) > 200:
        raise HTTPException(400, "Password must be 8 to 200 characters.")
    return email


def _rate_key(request: Request, email: str) -> list[str]:
    host = request.client.host if request.client else "unknown"
    return [f"e:{email}", f"ip:{host}"]


def check_rate(request: Request, email: str) -> None:
    now = time.time()
    for k in _rate_key(request, email):
        q = _fails[k]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= MAX_FAILS:
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in a few minutes.")


def record_fail(request: Request, email: str) -> None:
    for k in _rate_key(request, email):
        _fails[k].append(time.time())


def start_session(db: Session, response: Response, user: User) -> None:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        s = db.get(AuthSession, _token_hash(token))
        if s:
            db.delete(s)
            db.commit()
    response.delete_cookie(COOKIE, path="/")


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Sign in to continue.")
    s = db.get(AuthSession, _token_hash(token))
    if s is None:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    exp = s.expires_at.replace(tzinfo=None) if s.expires_at.tzinfo else s.expires_at
    if exp < utcnow().replace(tzinfo=None):
        db.delete(s)
        db.commit()
        raise HTTPException(401, "Your session has expired. Sign in again.")
    user = db.get(User, s.user_id)
    if user is None:
        raise HTTPException(401, "Account not found.")
    if user.disabled:
        raise HTTPException(403, "This account has been disabled by an administrator.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required.")
    return user


def should_be_admin(db: Session, email: str) -> bool:
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    if email in admins:
        return True
    return db.scalar(select(User.id).where(User.is_guest.is_(False)).limit(1)) is None  # first real account becomes admin


def user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))
