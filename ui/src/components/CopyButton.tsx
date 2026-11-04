import { AnimatePresence, motion } from "framer-motion";
import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { compact, modKey } from "../lib/format";
import { useStore } from "../lib/store";

const PARTICLES = Array.from({ length: 12 }, (_, i) => {
  const angle = (i / 12) * Math.PI * 2 + (i % 2 ? 0.2 : -0.1);
  const dist = 26 + (i % 3) * 10;
  return { x: Math.cos(angle) * dist, y: Math.sin(angle) * dist, size: 3 + (i % 3), hue: i % 3 };
});

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for non-secure contexts (e.g. LAN IP over http).
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

export function useCopyBundle() {
  const result = useStore((s) => s.result);
  const toast = useStore((s) => s.toast);
  const [burst, setBurst] = useState(0);
  const copy = useCallback(async () => {
    if (!result?.bundle) return false;
    const ok = await writeClipboard(result.bundle);
    if (ok) setBurst((b) => b + 1);
    else toast({ tone: "error", title: "Copy failed", body: "The browser blocked clipboard access." });
    return ok;
  }, [result, toast]);
  return { copy, burst, tokens: result?.stats.bundle_tokens ?? 0, disabled: !result?.bundle };
}

/** "Copy Optimized Prompt" with a morphing icon, shimmer sweep and particle burst. */
export function CopyButton({ burst, onCopy, tokens, disabled }: { burst: number; onCopy: () => void; tokens: number; disabled: boolean }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!burst) return;
    setCopied(true);
    const t = setTimeout(() => setCopied(false), 1900);
    return () => clearTimeout(t);
  }, [burst]);

  return (
    <motion.button
      onClick={onCopy}
      disabled={disabled}
      whileHover={disabled ? undefined : { y: -1 }}
      whileTap={disabled ? undefined : { scale: 0.95 }}
      transition={{ type: "spring", stiffness: 600, damping: 30 }}
      className={`group relative flex h-9 items-center gap-2 overflow-visible rounded-xl px-3.5 text-[12.5px] font-semibold text-white shadow-[0_8px_24px_-8px_rgb(var(--accent)/0.8)] transition-[filter,opacity] disabled:cursor-not-allowed disabled:opacity-40 ${
        copied ? "bg-ok" : "bg-accent"
      }`}
      data-testid="copy-button"
      title={`Copy optimized prompt (${modKey}⇧C)`}
    >
      <span className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl">
        <span className="absolute inset-y-0 -left-1/2 w-1/2 -skew-x-12 bg-white/25 opacity-0 transition-none group-hover:animate-shimmer group-hover:opacity-100" />
      </span>
      <span className="relative grid h-4 w-4 place-items-center">
        <AnimatePresence mode="popLayout" initial={false}>
          {copied ? (
            <motion.span
              key="check"
              initial={{ scale: 0, rotate: -90 }}
              animate={{ scale: 1, rotate: 0 }}
              exit={{ scale: 0, opacity: 0 }}
              transition={{ type: "spring", stiffness: 600, damping: 18 }}
            >
              <Check size={16} strokeWidth={3} />
            </motion.span>
          ) : (
            <motion.span key="copy" initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.4, opacity: 0 }}>
              <Copy size={15} />
            </motion.span>
          )}
        </AnimatePresence>
        {/* particle burst */}
        <AnimatePresence>
          {copied &&
            PARTICLES.map((p, i) => (
              <motion.span
                key={`${burst}-${i}`}
                className="pointer-events-none absolute left-1/2 top-1/2 rounded-full"
                style={{
                  width: p.size,
                  height: p.size,
                  marginLeft: -p.size / 2,
                  marginTop: -p.size / 2,
                  background: ["rgb(var(--callee))", "rgb(var(--accent))", "rgb(var(--caller))"][p.hue],
                }}
                initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
                animate={{ x: p.x, y: p.y, opacity: 0, scale: 0.4 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              />
            ))}
        </AnimatePresence>
      </span>
      <span className="relative overflow-hidden">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={copied ? "c" : "n"}
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -14, opacity: 0 }}
            transition={{ type: "spring", stiffness: 500, damping: 32 }}
            className="block whitespace-nowrap"
          >
            {copied ? `Copied · ${compact(tokens)} tokens` : "Copy optimized prompt"}
          </motion.span>
        </AnimatePresence>
      </span>
    </motion.button>
  );
}
