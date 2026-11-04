import { AnimatePresence, motion } from "framer-motion";
import { Gauge, Info } from "lucide-react";
import { compact } from "../lib/format";
import { useStore } from "../lib/store";
import { Odometer } from "./Odometer";

/** Top-right savings readout: "Saved 91.4% tokens — 142k down to 12.1k". */
export function TokenCounter() {
  const result = useStore((s) => s.result);
  const profile = useStore((s) => s.profile);
  const depth = useStore((s) => s.settings.depth);
  const repo = useStore((s) => s.repo);
  const targets = useStore((s) => s.targets);
  const pending = useStore((s) => s.pending);

  const repoTokens = result?.stats.repo_tokens ?? repo?.tokens ?? 0;
  const exact = result && result.query.depth === depth ? result.stats : null;
  // Past the depth where the graph saturates the profile stops: reuse its last point.
  const fromProfile = !exact && profile?.length ? profile.find((p) => p.depth === depth) ?? (depth > profile[profile.length - 1].depth ? profile[profile.length - 1] : undefined) : undefined;
  const bundle = exact ? exact.bundle_tokens : fromProfile ? fromProfile.tokens : result?.stats.bundle_tokens ?? 0;
  const saved = repoTokens ? Math.max(0, 100 * (1 - bundle / repoTokens)) : 0;
  const active = !!targets && (!!result || !!fromProfile);
  const tokenizerExact = result?.stats.tokenizer_exact ?? repo?.tokenizer_exact ?? true;

  const R = 22;
  const C = 2 * Math.PI * R;

  return (
    <motion.div
      layout
      className="glass pointer-events-auto relative overflow-hidden rounded-2xl px-4 py-3"
      data-testid="token-counter"
      transition={{ type: "spring", stiffness: 380, damping: 32 }}
    >
      <div className="pointer-events-none absolute -right-10 -top-14 h-36 w-36 rounded-full bg-accent/20 blur-3xl" />
      <AnimatePresence mode="wait" initial={false}>
        {active ? (
          <motion.div
            key="active"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18 }}
            className="relative flex items-center gap-3.5"
          >
            <svg width="56" height="56" viewBox="0 0 56 56" className="-rotate-90 shrink-0">
              <circle cx="28" cy="28" r={R} fill="none" stroke="rgb(var(--line))" strokeWidth="5" />
              <motion.circle
                cx="28"
                cy="28"
                r={R}
                fill="none"
                stroke="url(#savedGrad)"
                strokeWidth="5"
                strokeLinecap="round"
                strokeDasharray={C}
                initial={false}
                animate={{ strokeDashoffset: C * (1 - saved / 100) }}
                transition={{ type: "spring", stiffness: 90, damping: 20 }}
              />
              <defs>
                <linearGradient id="savedGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="rgb(var(--accent))" />
                  <stop offset="1" stopColor="rgb(var(--callee))" />
                </linearGradient>
              </defs>
            </svg>
            <div className="min-w-0">
              <div className="flex items-baseline gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-mute">
                Saved
                {pending && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
              </div>
              <div className="mt-1 text-[30px] font-semibold tracking-tight text-accent [text-shadow:0_0_24px_rgb(var(--accent)/0.35)]">
                <Odometer value={`${saved.toFixed(1)}%`} />
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[12px] text-mute">
                <Odometer value={compact(repoTokens)} className="text-fg/70" />
                <span className="text-faint">→</span>
                <Odometer value={compact(bundle)} className="font-semibold text-fg" />
                <span>tokens</span>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="idle"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18 }}
            className="relative flex items-center gap-3"
          >
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-elev text-mute">
              <Gauge size={18} />
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-mute">Repository</div>
              <div className="text-[20px] font-semibold tabular-nums tracking-tight">
                <Odometer value={compact(repoTokens)} /> <span className="text-[13px] font-medium text-mute">tokens</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {!tokenizerExact && (
        <div className="relative mt-2 flex items-center gap-1 text-[10.5px] text-faint" title="tiktoken vocabulary unavailable; counts are estimates (±5%)">
          <Info size={11} /> approximate token counts
        </div>
      )}
    </motion.div>
  );
}
