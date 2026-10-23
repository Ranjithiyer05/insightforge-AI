import { NextRequest, NextResponse } from "next/server";

// Visitors without a session never wait on the API: the main link goes straight to the public home page
// and other app pages go to sign-in.
const PUBLIC = ["/welcome", "/login", "/register"];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC.includes(pathname) || pathname.startsWith("/share/") || req.cookies.has("if_session")) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.search = "";
  if (pathname === "/") url.pathname = "/welcome";
  else { url.pathname = "/login"; url.searchParams.set("next", pathname + search); }
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/((?!api|_next|icon.svg|favicon.ico|.*\\.[a-z0-9]+$).*)"] };
