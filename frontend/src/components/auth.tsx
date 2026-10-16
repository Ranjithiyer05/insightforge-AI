"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export type User = { id: string; email: string; name: string; is_admin: boolean };
type Ctx = { user: User | null; loading: boolean; setUser: (u: User | null) => void; logout: () => Promise<void> };
const AuthCtx = createContext<Ctx>({ user: null, loading: true, setUser: () => {}, logout: async () => {} });
export const PUBLIC_ROUTES = ["/login", "/register"];
export const isPublicRoute = (p: string) => PUBLIC_ROUTES.includes(p) || p.startsWith("/share/");

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const path = usePathname();
  const router = useRouter();
  useEffect(() => {
    if (isPublicRoute(path)) { setLoading(false); return; }
    api<User>("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, [path]);
  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
    router.push("/login");
  };
  return <AuthCtx.Provider value={{ user, loading, setUser, logout }}>{children}</AuthCtx.Provider>;
}
export const useAuth = () => useContext(AuthCtx);
