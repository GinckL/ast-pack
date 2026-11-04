import { AnimatePresence, motion } from "framer-motion";
import { Bug, Clock, CornerDownLeft, FileCode2, Loader2, Search, Sparkles, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { KIND_GLYPH } from "../lib/colors";
import { detectTrace, modKey } from "../lib/format";
import { socket, useStore } from "../lib/store";
import type { SymbolInfo } from "../lib/types";

const FILE_LINE = /^[^\s:]+\.[a-z]{1,4}:\d+(:\d+)?$/i;

const KIND_COLOR: Record<string, string> = {
  function: "var(--callee)",
  method: "var(--callee)",
  class: "var(--type)",
  struct: "var(--type)",
  interface: "var(--type)",
  trait: "var(--type)",
  enum: "var(--type)",
  type: "var(--type)",
  const: "var(--value)",
  static: "var(--value)",
  variable: "var(--value)",
};

type Row =
  | { kind: "symbol"; sym: SymbolInfo }
  | { kind: "recent"; text: string }
  | { kind: "suggest"; text: string };

export function CommandBar({ inputRef }: { inputRef: React.RefObject<HTMLTextAreaElement> }) {
  const input = useStore((s) => s.input);
  const setInput = useStore((s) => s.setInput);
  const submit = useStore((s) => s.submit);
  const pending = useStore((s) => s.pending);
  const error = useStore((s) => s.error);
  const recents = useStore((s) => s.recents);
  const conn = useStore((s) => s.conn);
  const [focused, setFocused] = useState(false);
  const [results, setResults] = useState<SymbolInfo[]>([]);
  const [sel, setSel] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const trace = useMemo(() => (input.includes("\n") || /panicked at/.test(input) ? detectTrace(input) : null), [input]);
  const isFileLine = FILE_LINE.test(input.trim());
  const query = input.trim();

  // Live search (latest-wins on the socket).
  useEffect(() => {
    if (!query || trace || query.includes("\n") || query.length > 120) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => {
      socket
        .search(query, 8)
        .then((r) => {
          if (r) {
            setResults(r);
            setSel(0);
          }
        })
        .catch(() => setResults([]));
    }, 40);
    return () => clearTimeout(t);
  }, [query, trace, conn]);

  // Auto-grow textarea.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "0px";
    // A pasted trace collapses to one line once the bar loses focus.
    const max = focused ? 168 : trace ? 20 : 168;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
  }, [input, inputRef, focused, trace]);

  const rows: Row[] = useMemo(() => {
    if (error && !dismissed) return error.suggestions.map((s) => ({ kind: "suggest" as const, text: s.replace(/ \(.*\)$/, "") }));
    if (!query) return recents.map((r) => ({ kind: "recent" as const, text: r }));
    if (trace || isFileLine) return [];
    return results.map((sym) => ({ kind: "symbol" as const, sym }));
  }, [error, dismissed, query, recents, trace, isFileLine, results]);

  const open = focused && !dismissed && (rows.length > 0 || !!error);

  useEffect(() => {
    setDismissed(false);
  }, [input, error]);

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-row="${sel}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const done = () => {
    setDismissed(true);
    // Hand the keyboard back to the app so [ ] 1 2 3 C work right away.
    inputRef.current?.blur();
  };

  const choose = (row: Row | undefined) => {
    if (!row) {
      submit();
    } else if (row.kind === "symbol") {
      const target = `${row.sym.path}::${row.sym.qualname}`;
      setInput(target);
      submit(target);
    } else {
      setInput(row.text);
      submit(row.text);
    }
    done();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "ArrowDown" && open && rows.length) {
      e.preventDefault();
      setSel((s) => (s + 1) % rows.length);
    } else if (e.key === "ArrowUp" && open && rows.length) {
      e.preventDefault();
      setSel((s) => (s - 1 + rows.length) % rows.length);
    } else if (e.key === "Tab" && open && rows[sel]) {
      e.preventDefault();
      const r = rows[sel];
      setInput(r.kind === "symbol" ? r.sym.qualname : r.text);
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.metaKey || e.ctrlKey || trace || isFileLine || !open) {
        submit();
        done();
      } else {
        choose(rows[sel]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (open) setDismissed(true);
      else (e.target as HTMLTextAreaElement).blur();
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const text = e.clipboardData.getData("text");
    if (text.includes("\n") && detectTrace(text)) {
      e.preventDefault();
      setInput(text);
      submit(text);
      done();
    }
  };

  const LeadIcon = trace ? Bug : isFileLine ? FileCode2 : Search;

  return (
    <div className="pointer-events-auto relative w-full" data-testid="command-bar">
      <motion.div
        initial={{ y: -24, opacity: 0, scale: 0.98 }}
        animate={{ y: 0, opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 300, damping: 26 }}
        className={`glass relative overflow-hidden rounded-2xl transition-shadow duration-200 ${
          focused ? "shadow-[0_0_0_1px_rgb(var(--accent)/0.55),0_0_0_6px_rgb(var(--accent)/0.12),0_24px_60px_-12px_rgb(0_0_0/0.6)]" : ""
        }`}
      >
        <div className="flex items-start gap-3 px-4 py-3">
          <motion.div
            key={trace ? "t" : isFileLine ? "f" : "s"}
            initial={{ scale: 0.6, rotate: -20, opacity: 0 }}
            animate={{ scale: 1, rotate: 0, opacity: 1 }}
            transition={{ type: "spring", stiffness: 500, damping: 26 }}
            className={`mt-[3px] ${trace ? "text-danger" : "text-mute"}`}
          >
            <LeadIcon size={18} />
          </motion.div>
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 120)}
            placeholder="Function name, file:line, or paste a stack trace…"
            className={`scroll-thin min-w-0 flex-1 resize-none bg-transparent text-[15px] leading-6 text-fg outline-none placeholder:text-faint ${
              trace ? "font-mono text-[12px] leading-5" : ""
            } ${trace && !focused ? "overflow-hidden" : ""}`}
            aria-label="Pack target"
            data-testid="command-input"
          />
          <div className="mt-[2px] flex shrink-0 items-center gap-2">
            {pending && <Loader2 size={16} className="animate-spin text-accent" />}
            {input && (
              <button
                onClick={() => {
                  setInput("");
                  inputRef.current?.focus();
                }}
                className="grid h-6 w-6 place-items-center rounded-md text-faint transition-colors hover:bg-elev hover:text-fg"
                aria-label="Clear"
              >
                <X size={14} />
              </button>
            )}
            {!focused && (
              <span className="flex items-center gap-1">
                <kbd className="kbd">{modKey}</kbd>
                <kbd className="kbd">K</kbd>
              </span>
            )}
          </div>
        </div>
        {/* progress shimmer */}
        <AnimatePresence>
          {pending && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-x-0 bottom-0 h-[2px] overflow-hidden"
            >
              <div className="h-full w-1/2 animate-shimmer bg-gradient-to-r from-transparent via-accent to-transparent" />
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence initial={false}>
          {trace && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-line/70"
            >
              <div className="flex items-center gap-2 px-4 py-2 text-[12px] text-mute">
                <Sparkles size={13} className="text-danger" />
                <span>
                  <span className="font-medium text-fg">{trace.language} stack trace</span> · {trace.frames} frame{trace.frames === 1 ? "" : "s"} —
                  every frame inside the repo becomes an entry point
                </span>
                <span className="ml-auto flex items-center gap-1">
                  <kbd className="kbd">
                    <CornerDownLeft size={10} />
                  </kbd>
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.99, transition: { duration: 0.1 } }}
            transition={{ type: "spring", stiffness: 520, damping: 36 }}
            className="glass absolute inset-x-0 top-[calc(100%+8px)] z-40 origin-top overflow-hidden rounded-2xl"
            data-testid="command-results"
          >
            {error && !dismissed && (
              <div className="flex items-center gap-2 border-b border-line/70 px-4 py-2.5 text-[12.5px]">
                <span className="h-1.5 w-1.5 rounded-full bg-danger" />
                <span className="text-fg">{error.message}</span>
                {error.suggestions.length > 0 && <span className="text-mute">— did you mean:</span>}
              </div>
            )}
            {!query && rows.length > 0 && (
              <div className="px-4 pb-1 pt-2.5 text-[10.5px] font-medium uppercase tracking-[0.12em] text-faint">Recent</div>
            )}
            <div ref={listRef} className="scroll-thin max-h-[340px] overflow-y-auto p-1.5">
              {rows.map((row, i) => (
                <button
                  key={row.kind === "symbol" ? row.sym.id : `${row.kind}:${row.text}`}
                  data-row={i}
                  onMouseMove={() => setSel(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(row)}
                  className="relative flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left"
                >
                  {sel === i && (
                    <motion.span
                      layoutId="cmd-sel"
                      className="absolute inset-0 rounded-xl bg-elev"
                      transition={{ type: "spring", stiffness: 700, damping: 45 }}
                    />
                  )}
                  {row.kind === "symbol" ? <SymbolRow sym={row.sym} query={query} /> : <TextRow text={row.text} recent={row.kind === "recent"} />}
                  {sel === i && (
                    <span className="relative ml-2 flex shrink-0 items-center gap-1 text-[11px] text-faint">
                      pack <kbd className="kbd"><CornerDownLeft size={10} /></kbd>
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-3 border-t border-line/70 px-4 py-2 text-[11px] text-faint">
              <span className="flex items-center gap-1"><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> select</span>
              <span className="flex items-center gap-1"><kbd className="kbd">⇥</kbd> complete</span>
              <span className="flex items-center gap-1"><kbd className="kbd">{modKey}</kbd><kbd className="kbd">↵</kbd> exact text</span>
              <span className="ml-auto truncate">or paste a stack trace</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function highlightMatch(text: string, query: string) {
  // Subsequence highlight, case-insensitive.
  const q = query.toLowerCase().split(/::|\./).pop() ?? "";
  if (!q) return text;
  const out: React.ReactNode[] = [];
  let qi = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (qi < q.length && ch.toLowerCase() === q[qi]) {
      out.push(
        <span key={i} className="text-accent">
          {ch}
        </span>,
      );
      qi++;
    } else {
      out.push(ch);
    }
  }
  return qi === q.length ? out : text;
}

function SymbolRow({ sym, query }: { sym: SymbolInfo; query: string }) {
  const color = KIND_COLOR[sym.kind] ?? "var(--faint)";
  return (
    <span className="relative flex min-w-0 flex-1 items-center gap-3">
      <span
        className="grid h-7 w-7 shrink-0 place-items-center rounded-lg font-mono text-[12px] font-bold"
        style={{ background: `rgb(${color} / 0.14)`, color: `rgb(${color})` }}
      >
        {KIND_GLYPH[sym.kind] ?? "·"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="truncate font-mono text-[13px] font-medium text-fg">{highlightMatch(sym.qualname, query)}</span>
          <span className="shrink-0 text-[11px] text-faint">{sym.kind}</span>
        </span>
        <span className="block truncate font-mono text-[11px] text-mute">
          {sym.path}:{sym.start_line}
          {sym.signature && <span className="text-faint"> — {sym.signature}</span>}
        </span>
      </span>
    </span>
  );
}

function TextRow({ text, recent }: { text: string; recent: boolean }) {
  return (
    <span className="relative flex min-w-0 flex-1 items-center gap-3">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-elev text-mute">
        {recent ? <Clock size={14} /> : <Sparkles size={14} />}
      </span>
      <span className="truncate font-mono text-[13px] text-fg">{text}</span>
    </span>
  );
}
