"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch JSON; optionally keep polling while `poll(data)` returns true. */
export function useApi<T = any>(path: string | null, opts: { poll?: (d: T) => boolean; interval?: number } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const [nonce, setNonce] = useState(0);
  const pollRef = useRef(opts.poll);
  pollRef.current = opts.poll;
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      setData(d);
      setError(null);
      return d;
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    let timer: any;
    let alive = true;
    const tick = async () => {
      const d = await load();
      if (alive && d && pollRef.current?.(d)) timer = setTimeout(tick, opts.interval ?? 1500);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [load, opts.interval, path, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload, setData };
}
