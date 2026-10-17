"""Untrusted file intake: validation, parsing and safe storage.

* Only .csv / .xlsx / .xlsm are accepted, and the content must match the
  extension (Excel files must be ZIP containers, CSV must decode as text).
* The user-supplied filename is never used to build a filesystem path; files
  are stored under a server-generated id, which rules out path traversal.
* Excel is parsed with openpyxl in read-only/data-only mode, so formulas are
  not evaluated and macros are never run.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import threading
from collections import OrderedDict
import io
import re
from pathlib import Path

import pandas as pd

from .config import settings

ALLOWED_EXT = {".csv": "csv", ".xlsx": "excel", ".xlsm": "excel"}


class UploadError(ValueError):
    pass


def safe_display_name(filename: str) -> str:
    name = Path(filename or "dataset").name  # strips any directory components
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120]
    return name or "dataset"


def detect_type(filename: str, head: bytes) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadError(f"Unsupported file type '{ext or 'none'}'. Upload a .csv, .xlsx or .xlsm file.")
    kind = ALLOWED_EXT[ext]
    if kind == "excel" and not head.startswith(b"PK\x03\x04"):
        raise UploadError("The file has an Excel extension but is not a valid Excel workbook.")
    if kind == "csv":
        if b"\x00" in head[:4096]:
            raise UploadError("The file looks binary, not like a CSV text file.")
    return kind


def parse_bytes(raw: bytes, kind: str, sheet: str | int | None = 0) -> pd.DataFrame:
    if kind == "csv":
        text = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise UploadError("Could not decode the CSV file as text.")
        try:
            df = pd.read_csv(io.StringIO(text), sep=sniff_delimiter(text[:65536].rsplit("\n", 1)[0]), nrows=settings.max_rows + 1, low_memory=False)
        except Exception as exc:  # pandas raises many types
            raise UploadError(f"Could not parse the CSV file: {str(exc)[:200]}") from exc
    else:
        try:
            df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet if sheet is not None else 0, engine="openpyxl")
        except Exception as exc:
            raise UploadError(f"Could not read the Excel workbook: {str(exc)[:200]}") from exc
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise UploadError("The file contains no data rows.")
    if df.shape[0] > settings.max_rows:
        raise UploadError(f"The file has more than {settings.max_rows:,} rows, which exceeds the configured limit.")
    df.columns = _dedupe_columns([str(c).strip() or f"column_{i+1}" for i, c in enumerate(df.columns)])
    return df


def sniff_delimiter(sample: str) -> str:
    """Pick the delimiter from a text sample so the fast C parser can be used."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _dedupe_columns(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        c = c[:120]
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def store_dataframe(dataset_id: str, df: pd.DataFrame) -> Path:
    if not re.fullmatch(r"ds_[0-9a-f]{12}", dataset_id):
        raise ValueError("invalid dataset id")
    folder = settings.uploads_dir / dataset_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "data.csv"
    df.to_csv(path, index=False)
    _save_blob(dataset_id, path)
    return path


def _save_blob(dataset_id: str, path: Path) -> None:
    """Keep a gzip copy in the database so the file survives restarts on hosts with an ephemeral disk."""
    from .db import DatasetBlob, SessionLocal
    data = gzip.compress(path.read_bytes(), compresslevel=6)
    if len(data) > settings.db_blob_max_mb * 1024 * 1024:
        return  # too large for the database copy; the disk copy is still used
    db = SessionLocal()
    try:
        db.merge(DatasetBlob(dataset_id=dataset_id, data=data))
        db.commit()
    finally:
        db.close()


def _restore_blob(dataset_id: str, path: Path) -> bool:
    from .db import DatasetBlob, SessionLocal
    db = SessionLocal()
    try:
        blob = db.get(DatasetBlob, dataset_id)
        if blob is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.decompress(blob.data))
        tmp.replace(path)
        return True
    finally:
        db.close()


class DatasetFileMissing(FileNotFoundError):
    pass


def dataset_path(dataset_id: str) -> Path:
    if not re.fullmatch(r"ds_[0-9a-f]{12}", dataset_id):
        raise ValueError("invalid dataset id")
    path = (settings.uploads_dir / dataset_id / "data.csv").resolve()
    if settings.uploads_dir.resolve() not in path.parents:
        raise ValueError("path escapes the uploads directory")
    if not path.exists() and not _restore_blob(dataset_id, path):
        raise DatasetFileMissing("The data file for this dataset is no longer on the server (it was removed by a restart or retention). Upload it again.")
    return path


_cache: "OrderedDict[str, tuple[float, pd.DataFrame]]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_SIZE = 4


def load_dataset(dataset_id: str) -> pd.DataFrame:
    """Parsed dataset, cached by file modification time. Callers get a copy so the cache is never mutated."""
    path = dataset_path(dataset_id)
    mtime = path.stat().st_mtime
    with _cache_lock:
        hit = _cache.get(dataset_id)
        if hit and hit[0] == mtime:
            _cache.move_to_end(dataset_id)
            return hit[1].copy()
    df = pd.read_csv(path, low_memory=False)
    with _cache_lock:
        _cache[dataset_id] = (mtime, df)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return df.copy()


def forget_dataset(dataset_id: str) -> None:
    with _cache_lock:
        _cache.pop(dataset_id, None)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralise spreadsheet formula injection in exported CSV cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIX):
        return "'" + value
    return value
