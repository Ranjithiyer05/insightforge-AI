"use client";
import { createContext, useContext, useEffect, useState } from "react";

type Current = { projectId?: string | null; projectName?: string | null; datasetId?: string | null; datasetName?: string | null };
const Ctx = createContext<{ current: Current; setCurrent: (c: Current) => void }>({ current: {}, setCurrent: () => {} });

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [current, setCur] = useState<Current>({});
  useEffect(() => {
    try { setCur(JSON.parse(localStorage.getItem("if-current") || "{}")); } catch {}
  }, []);
  const setCurrent = (c: Current) => {
    const next = { ...current, ...c };
    setCur(next);
    try { localStorage.setItem("if-current", JSON.stringify(next)); } catch {}
  };
  return <Ctx.Provider value={{ current, setCurrent }}>{children}</Ctx.Provider>;
}
export const useWorkspace = () => useContext(Ctx);
