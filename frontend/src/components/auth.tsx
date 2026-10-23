"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export type User = { id: string; email: string; name: string; is_admin: boolean; is_guest?: boolean };
type Ctx = { user: User | null; loading: boolean; error: string | null; retry: () => void; setUser: (u: User | null) => void; logout: () => Promise<void> };
const AuthCtx = createContext<Ctx>({ user: null, loading: true, error: null, retry: () => {}, setUser: () => {}, logout: async () => {} });
export const PUBLIC_ROUTES = ["/login", "/register", "/welcome"];
export const isPublicRoute = (p: string) => PUBLIC_ROUTES.includes(p) || p.startsWith("/share/");

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const path = usePathname();
  const router = useRouter();
  useEffect(() => {
    if (isPublicRoute(path)) { setLoading(false); return; }
    setError(null);
    api<User>("/auth/me").then(setUser)
      .catch((e: any) => { setUser(null); if (e?.status !== 401) setError(e?.message || "The server could not be reached."); })
      .finally(() => setLoading(false));
  }, [path, attempt]);
  // While the server is unreachable (for example waking up on free hosting), retry every 10 seconds.
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setAttempt((a) => a + 1), 10000);
    return () => clearTimeout(t);
  }, [error, attempt]);
  const retry = () => { setLoading(true); setAttempt((a) => a + 1); };
  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
    router.push("/login");
  };
  return <AuthCtx.Provider value={{ user, loading, error, retry, setUser, logout }}>{children}</AuthCtx.Provider>;
}
export const useAuth = () => useContext(AuthCtx);
