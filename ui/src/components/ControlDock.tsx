import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeftRight, ArrowLeft, ArrowRight, Boxes, FlaskConical, ShieldCheck, SlidersHorizontal, Wallet } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { compact } from "../lib/format";
import { MAX_DEPTH, useStore } from "../lib/store";
import type { Direction } from "../lib/types";

const DIRECTIONS: { id: Direction; label: string; icon: typeof ArrowLeftRight; key: string }[] = [
  { id: "both", label: "Both", icon: ArrowLeftRight, key: "1" },
  { id: "callers", label: "Callers", icon: ArrowLeft, key: "2" },
  { id: "callees", label: "Callees", icon: ArrowRight, key: "3" },
];

const BUDGETS: (number | null)[] = [null, 4000, 8000, 16000, 32000];

export function ControlDock() {
  const settings = useStore((s) => s.settings);
  const setSettings = useStore((s) => s.setSettings);
  const setDepth = useStore((s) => s.setDepth);
  const profile = useStore((s) => s.profile);
  const targets = useStore((s) => s.targets);
  const [optsOpen, setOptsOpen] = useState(false);
  const optsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!optsOpen) return;
    const close = (e: MouseEvent) => {
      if (optsRef.current && !optsRef.current.contains(e.target as Node)) setOptsOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [optsOpen]);

  const maxTok = Math.max(1, ...(profile ?? []).map((p) => p.tokens));
  const depth = settings.depth;

  return (
    <motion.div
      initial={{ y: 40, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 26, delay: 0.1 }}
      className="glass pointer-events-auto flex items-stretch gap-1 rounded-2xl p-1.5"
      data-testid="dock"
    >
      {/* Hop depth */}
      <div className="flex w-[300px] flex-col justify-center rounded-xl px-3 py-1.5">
        <div className="flex items-center justify-between text-[11px]">
          <span className="font-medium uppercase tracking-[0.12em] text-mute">Hop depth</span>
          <span className="flex items-center gap-1.5 text-faint">
            <kbd className="kbd">[</kbd>
            <kbd className="kbd">]</kbd>
          </span>
        </div>
        <div className="relative mt-1.5 h-[46px]">
          {/* Token profile bars per depth */}
          <div className="absolute inset-x-[9px] bottom-[13px] top-0 flex items-end justify-between">
            {Array.from({ length: MAX_DEPTH + 1 }, (_, d) => {
              const last = profile?.length ? profile[profile.length - 1] : undefined;
              const p = profile?.find((x) => x.depth === d) ?? (last && d > last.depth ? last : undefined);
              const hgt = p && targets ? Math.max(3, (p.tokens / maxTok) * 26) : 3;
              const on = d <= depth;
              return (
                <div key={d} className="relative flex w-0 flex-col items-center">
                  <AnimatePresence>
                    {p && targets && d === depth && (
                      <motion.span
                        initial={{ opacity: 0, y: 4, scale: 0.9 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 4 }}
                        className="absolute whitespace-nowrap rounded-md bg-accent/15 px-1 text-[10px] font-semibold tabular-nums text-accent"
                        style={{ bottom: hgt + 4 }}
                      >
                        {compact(p.tokens)}
                      </motion.span>
                    )}
                  </AnimatePresence>
                  <motion.div
                    className="w-[18px] rounded-[4px]"
                    initial={false}
                    animate={{
                      height: hgt,
                      backgroundColor: on ? "rgb(var(--accent) / 0.55)" : "rgb(var(--line) / 0.9)",
                    }}
                    transition={{ type: "spring", stiffness: 300, damping: 26 }}
                  />
                </div>
              );
            })}
          </div>
          <div className="absolute inset-x-[9px] bottom-[9px] h-1 rounded-full bg-line" />
          <motion.div
            className="absolute bottom-[9px] left-[9px] h-1 rounded-full bg-gradient-to-r from-accent/70 to-accent"
            initial={false}
            animate={{ width: `calc((100% - 18px) * ${depth / MAX_DEPTH})` }}
            transition={{ type: "spring", stiffness: 400, damping: 34 }}
          />
          <input
            type="range"
            className="depth absolute inset-x-0 bottom-0"
            min={0}
            max={MAX_DEPTH}
            step={1}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            aria-label="Hop depth"
            data-testid="depth-slider"
          />
        </div>
        <div className="flex justify-between px-[5px] text-[10px] tabular-nums text-faint">
          {Array.from({ length: MAX_DEPTH + 1 }, (_, d) => (
            <button
              key={d}
              onClick={() => setDepth(d)}
              className={`w-2.5 text-center transition-colors ${d === depth ? "font-semibold text-fg" : "hover:text-mute"}`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      <div className="my-2 w-px bg-line" />

      {/* Direction */}
      <div className="flex flex-col justify-center px-2">
        <span className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-[0.12em] text-mute">Walk</span>
        <div className="relative flex rounded-lg bg-elev p-0.5">
          {DIRECTIONS.map((d) => {
            const on = settings.direction === d.id;
            const Icon = d.icon;
            return (
              <button
                key={d.id}
                onClick={() => setSettings({ direction: d.id })}
                className={`relative z-10 flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors ${
                  on ? "text-fg" : "text-mute hover:text-fg"
                }`}
                title={`${d.label} (${d.key})`}
              >
                {on && (
                  <motion.span
                    layoutId="dir-pill"
                    className="absolute inset-0 -z-10 rounded-md bg-panel shadow-[0_1px_3px_rgb(0_0_0/0.25),0_0_0_1px_rgb(var(--line))]"
                    transition={{ type: "spring", stiffness: 500, damping: 38 }}
                  />
                )}
                <Icon size={13} />
                {d.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="my-2 w-px bg-line" />

      {/* Options */}
      <div ref={optsRef} className="relative flex items-center px-1">
        <button
          onClick={() => setOptsOpen((o) => !o)}
          className={`flex h-full flex-col items-center justify-center gap-1 rounded-xl px-3 text-[11px] font-medium transition-colors ${
            optsOpen ? "bg-elev text-fg" : "text-mute hover:bg-elev/70 hover:text-fg"
          }`}
          aria-expanded={optsOpen}
          data-testid="options-button"
        >
          <SlidersHorizontal size={16} />
          Options
          {settings.maxTokens && <span className="rounded bg-accent/15 px-1 text-[10px] text-accent">{compact(settings.maxTokens)}</span>}
        </button>
        <AnimatePresence>
          {optsOpen && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.1 } }}
              transition={{ type: "spring", stiffness: 480, damping: 34 }}
              className="glass absolute bottom-[calc(100%+12px)] right-0 w-[300px] origin-bottom-right rounded-2xl p-2"
            >
              <Toggle
                icon={Boxes}
                label="Type definitions & constants"
                hint="Pull in classes, structs, interfaces and consts the code uses"
                on={settings.includeTypes}
                onChange={(v) => setSettings({ includeTypes: v })}
              />
              <Toggle
                icon={FlaskConical}
                label="Follow test files"
                hint="Tests are skipped unless the target is a test"
                on={settings.includeTests}
                onChange={(v) => setSettings({ includeTests: v })}
              />
              <Toggle
                icon={ShieldCheck}
                label="Exact edges only"
                hint="Drop calls matched by name on untyped receivers"
                on={settings.exactOnly}
                onChange={(v) => setSettings({ exactOnly: v })}
              />
              <Toggle
                icon={SlidersHorizontal}
                label="Strip comments"
                hint="Remove comment-only lines from kept code"
                on={settings.stripComments}
                onChange={(v) => setSettings({ stripComments: v })}
              />
              <div className="mt-1 rounded-xl px-2.5 py-2">
                <div className="mb-2 flex items-center gap-2 text-[12.5px] font-medium">
                  <Wallet size={14} className="text-mute" /> Token budget
                </div>
                <div className="flex gap-1">
                  {BUDGETS.map((b) => (
                    <button
                      key={String(b)}
                      onClick={() => setSettings({ maxTokens: b })}
                      className={`flex-1 rounded-lg py-1.5 text-[11.5px] font-medium tabular-nums transition-colors ${
                        settings.maxTokens === b ? "bg-accent text-white" : "bg-elev text-mute hover:text-fg"
                      }`}
                    >
                      {b === null ? "∞" : compact(b)}
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function Toggle({
  icon: Icon,
  label,
  hint,
  on,
  onChange,
}: {
  icon: typeof Boxes;
  label: string;
  hint: string;
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!on)}
      className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-elev/80"
      role="switch"
      aria-checked={on}
    >
      <Icon size={14} className="shrink-0 text-mute" />
      <span className="min-w-0 flex-1">
        <span className="block text-[12.5px] font-medium">{label}</span>
        <span className="block truncate text-[11px] text-faint">{hint}</span>
      </span>
      <span className={`relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors ${on ? "bg-accent" : "bg-line"}`}>
        <motion.span
          className="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow"
          initial={false}
          animate={{ left: on ? 14 : 2 }}
          transition={{ type: "spring", stiffness: 700, damping: 35 }}
        />
      </span>
    </button>
  );
}
