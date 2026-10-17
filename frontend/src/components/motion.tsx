"use client";
import { animate, motion, MotionConfig, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

/** Honour the OS "reduce motion" setting everywhere. */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

const ease = [0.22, 1, 0.36, 1] as const;

export function PageTransition({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <motion.div key={id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28, ease }}>
      {children}
    </motion.div>
  );
}

export function Stagger({ children, className, delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div className={className} initial="hidden" animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: delay } } }}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { duration: 0.35, ease } } }}>
      {children}
    </motion.div>
  );
}

/** Counts up to `value` once it scrolls into view. Shows the final value immediately under reduced motion. */
export function AnimatedNumber({ value, format = (n) => Math.round(n).toLocaleString(), className }: { value: number | null | undefined; format?: (n: number) => string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (value == null || !Number.isFinite(value)) return;
    if (reduce || !inView) { if (reduce) setShown(value); return; }
    const c = animate(0, value, { duration: 0.9, ease, onUpdate: setShown });
    return () => c.stop();
  }, [value, inView, reduce]);
  return <span ref={ref} className={className}>{value == null || !Number.isFinite(value) ? "—" : format(shown)}</span>;
}

export { motion };
