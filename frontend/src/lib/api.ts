export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...rest,
    headers: { ...(json !== undefined ? { "content-type": "application/json" } : {}), ...(headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const b = await res.json();
      if (typeof b.detail === "string") msg = b.detail;
      else if (Array.isArray(b.detail)) msg = b.detail.map((d: any) => d.msg).join("; ");
    } catch {}
    if (res.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/register") && !location.pathname.startsWith("/share/")) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}

export function uploadWithProgress(file: File, projectId: string | null, onProgress: (pct: number) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets/upload");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let body: any = {};
      try { body = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    const fd = new FormData();
    fd.append("file", file);
    if (projectId) fd.append("project_id", projectId);
    xhr.send(fd);
  });
}

export const download = (path: string) => {
  const a = document.createElement("a");
  a.href = `/api${path}`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
};
