"use client";
import { Check, Copy } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "./ui/button";

const KW = /\b(import|from|as|def|return|if|elif|else|for|in|while|not|and|or|is|None|True|False|lambda|try|except|raise|with|class|SELECT|FROM|WHERE|GROUP|BY|ORDER|AS|SUM|COUNT|DISTINCT|JOIN|ON|LIMIT)\b/g;

function highlight(line: string) {
  const esc = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const hash = esc.indexOf("#");
  let code = esc, comment = "";
  if (hash >= 0 && !/["'].*#.*["']/.test(esc.slice(0, hash + 1))) {
    code = esc.slice(0, hash);
    comment = esc.slice(hash);
  }
  code = code
    .replace(/("[^"]*"|'[^']*')/g, '<span class="code-str">$1</span>')
    .replace(/(?<![\w.])(\d+\.?\d*)(?![\w])/g, '<span class="code-num">$1</span>')
    .replace(KW, '<span class="code-kw">$1</span>');
  return code + (comment ? `<span class="code-com">${comment}</span>` : "");
}

export function CodeViewer({ code, maxHeight = 420, filename }: { code: string; maxHeight?: number; filename?: string }) {
  const [copied, setCopied] = useState(false);
  const lines = useMemo(() => code.split("\n").map(highlight), [code]);
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-[var(--code-bg)]">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="font-mono text-[11.5px] text-fg-3">{filename ?? "analysis.py"} · {lines.length} lines · executed in sandbox</span>
        <Button variant="ghost" size="sm" onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
          {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-auto p-3 text-[12px] leading-[1.6] scrollbar-thin" style={{ maxHeight }}>
        <code className="font-mono">
          {lines.map((l, i) => (
            <div key={i} className="flex">
              <span className="mr-4 w-8 shrink-0 select-none text-right text-fg-3/60 num">{i + 1}</span>
              <span dangerouslySetInnerHTML={{ __html: l || " " }} />
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}
