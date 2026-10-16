// Runtime proxy to the FastAPI backend. BACKEND_URL is read per request (not baked in at build time)
// and never sent to the browser.
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const HOP = ["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const url = `${base}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers(req.headers);
  HOP.forEach((h) => headers.delete(h));
  const init: RequestInit & { duplex?: string } = { method: req.method, headers, redirect: "manual" };
  if (!["GET", "HEAD"].includes(req.method)) { init.body = req.body; init.duplex = "half"; }
  let res: Response;
  try { res = await fetch(url, init); } catch {
    return Response.json({ detail: "The analysis server is not reachable. On free hosting it may be waking up; try again in a minute." }, { status: 502 });
  }
  const out = new Headers(res.headers);
  HOP.forEach((h) => out.delete(h));
  return new Response(res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
