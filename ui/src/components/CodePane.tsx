import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronRight, FileText, Flame, ListTree, PanelRightClose } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { compact, dirname, basename, rangesLabel } from "../lib/format";
import { tokenize, type Tok } from "../lib/highlight";
import { useStore } from "../lib/store";
import type { FileRender, Format, PackResult, Segment, SliceNode } from "../lib/types";
import { CopyButton } from "./CopyButton";

const LANG_DOT: Record<string, string> = {
  python: "#3b82f6",
  typescript: "#3178c6",
  tsx: "#38bdf8",
  javascript: "#eab308",
  go: "#00add8",
  rust: "#f97316",
};

const FORMATS: { id: Format; label: string }[] = [
  { id: "markdown", label: "MD" },
  { id: "xml", label: "XML" },
  { id: "plain", label: "Plain" },
];

interface CopyProps {
  burst: number;
  onCopy: () => void;
  tokens: number;
  disabled: boolean;
}

export function CodePane({ copy }: { copy: CopyProps }) {
  const result = useStore((s) => s.result);
  const toggleCode = useStore((s) => s.toggleCode);
  const format = useStore((s) => s.settings.format);
  const setSettings = useStore((s) => s.setSettings);
  const prompt = useStore((s) => s.settings.prompt);
  const focus = useStore((s) => s.focus);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [taskOpen, setTaskOpen] = useState(false);
  const [draft, setDraft] = useState(prompt);

  useEffect(() => setDraft(prompt), [prompt]);
  useEffect(() => {
    if (draft === prompt) return;
    const t = setTimeout(() => setSettings({ prompt: draft }), 350);
    return () => clearTimeout(t);
  }, [draft, prompt, setSettings]);

  // Scroll to a focused file/line (from graph clicks, trace frames).
  useEffect(() => {
    if (!focus || !scrollRef.current) return;
    const root = scrollRef.current;
    const t = setTimeout(() => {
      const fileEl = root.querySelector<HTMLElement>(`[data-file="${CSS.escape(focus.path)}"]`);
      if (!fileEl) return;
      const lineEl =
        fileEl.querySelector<HTMLElement>(`[data-line="${focus.line}"]`) ??
        [...fileEl.querySelectorAll<HTMLElement>("[data-line]")].find((el) => Number(el.dataset.line) >= focus.line) ??
        fileEl;
      const top = lineEl.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 90;
      root.scrollTo({ top, behavior: "smooth" });
      lineEl.animate(
        [{ backgroundColor: "rgb(var(--accent) / 0.35)" }, { backgroundColor: "rgb(var(--accent) / 0)" }],
        { duration: 1400, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" },
      );
    }, 60);
    return () => clearTimeout(t);
  }, [focus]);

  const nodesByFile = useMemo(() => {
    const m = new Map<string, SliceNode[]>();
    for (const n of result?.nodes ?? []) {
      if (n.role === "container") continue;
      const list = m.get(n.path) ?? [];
      list.push(n);
      m.set(n.path, list);
    }
    return m;
  }, [result]);

  return (
    <div className="flex h-full flex-col" data-testid="code-pane">
      <div className="flex items-center gap-2 border-b border-line/80 px-4 py-3">
        <ListTree size={16} className="text-mute" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold">Context bundle</div>
          <div className="truncate text-[11.5px] text-mute">
            {result ? (
              <>
                {result.stats.symbols} symbols · {result.stats.files} files · {compact(result.stats.bundle_tokens)} tokens ·{" "}
                {Math.round(result.stats.elapsed_ms)} ms
              </>
            ) : (
              "Pack a target to preview the prompt"
            )}
          </div>
        </div>
        <div className="flex rounded-lg bg-elev p-0.5">
          {FORMATS.map((f) => (
            <button
              key={f.id}
              onClick={() => setSettings({ format: f.id })}
              className={`relative rounded-md px-2 py-1 text-[11px] font-semibold transition-colors ${format === f.id ? "text-fg" : "text-faint hover:text-mute"}`}
            >
              {format === f.id && (
                <motion.span layoutId="fmt-pill" className="absolute inset-0 rounded-md bg-panel shadow-[0_0_0_1px_rgb(var(--line))]" />
              )}
              <span className="relative">{f.label}</span>
            </button>
          ))}
        </div>
        <CopyButton {...copy} />
        <button
          onClick={() => toggleCode(false)}
          className="grid h-8 w-8 place-items-center rounded-lg text-faint transition-colors hover:bg-elev hover:text-fg"
          title="Hide code pane (\)"
        >
          <PanelRightClose size={16} />
        </button>
      </div>

      <div className="border-b border-line/60 px-4 py-2">
        <button
          onClick={() => setTaskOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 text-left text-[11.5px] font-medium text-mute hover:text-fg"
        >
          <motion.span animate={{ rotate: taskOpen ? 90 : 0 }} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
            <ChevronRight size={13} />
          </motion.span>
          Task for the model {prompt && !taskOpen && <span className="truncate font-normal text-faint">— {prompt}</span>}
        </button>
        <AnimatePresence initial={false}>
          {taskOpen && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={2}
                placeholder="e.g. Why does processPayment charge twice when the gateway times out?"
                className="scroll-thin mt-2 w-full resize-none rounded-lg border border-line bg-elev/60 px-2.5 py-2 text-[12.5px] outline-none placeholder:text-faint focus:border-accent/60"
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div ref={scrollRef} className="scroll-thin relative flex-1 overflow-y-auto px-3 pb-24 pt-3">
        {result ? (
          <>
            {result.trace && <TracePanel result={result} />}
            {result.dropped.length > 0 && (
              <div className="mb-3 flex items-center gap-2 rounded-xl border border-caller/30 bg-caller/10 px-3 py-2 text-[12px] text-fg">
                <AlertTriangle size={14} className="text-caller" />
                {result.dropped.length} farthest symbols dropped to fit the {compact(result.query.max_tokens ?? 0)}-token budget
              </div>
            )}
            {result.files.map((f, i) => (
              <FileCard key={f.path} file={f} index={i} nodes={nodesByFile.get(f.path) ?? []} />
            ))}
          </>
        ) : (
          <EmptyCode />
        )}
      </div>
    </div>
  );
}

function EmptyCode() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-2xl bg-elev text-mute">
        <FileText size={22} />
      </div>
      <div className="text-[13px] font-medium">No slice yet</div>
      <div className="max-w-[300px] text-[12px] leading-relaxed text-mute">
        The files of your context bundle show up here, with unrelated code collapsed into expandable pills.
      </div>
    </div>
  );
}

function TracePanel({ result }: { result: PackResult }) {
  const trace = result.trace!;
  const focusLine = useStore((s) => s.focusLine);
  const frames = trace.frames.filter((f) => f.repo_path);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 overflow-hidden rounded-xl border border-danger/30 bg-danger/[0.07]"
      data-testid="trace-panel"
    >
      <div className="flex items-start gap-2 px-3 py-2.5">
        <Flame size={15} className="mt-0.5 shrink-0 text-danger" />
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-danger">{trace.language} crash</div>
          {trace.error && <div className="mt-0.5 break-words font-mono text-[12px] text-fg">{trace.error}</div>}
        </div>
      </div>
      <div className="border-t border-danger/20 px-1.5 py-1">
        {frames.map((f, i) => {
          const crash = trace.crash_site && f.repo_path === trace.crash_site.repo_path && f.line === trace.crash_site.line;
          return (
            <button
              key={`${f.repo_path}:${f.line}:${i}`}
              onClick={() => focusLine(f.repo_path!, f.line)}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left font-mono text-[11.5px] transition-colors hover:bg-danger/10"
            >
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${crash ? "bg-danger shadow-[0_0_8px_rgb(var(--danger))]" : "bg-faint"}`} />
              <span className="truncate text-fg">{f.function ?? "frame"}</span>
              <span className="ml-auto shrink-0 text-mute">
                {basename(f.repo_path!)}:{f.line}
              </span>
            </button>
          );
        })}
      </div>
    </motion.div>
  );
}

const FileCard = memo(function FileCard({ file, index, nodes }: { file: FileRender; index: number; nodes: SliceNode[] }) {
  const [tokens, setTokens] = useState<Tok[][] | null>(null);
  const [near, setNear] = useState(index < 3);
  const ref = useRef<HTMLElement>(null);
  const hoverId = useStore((s) => s.hoverId);
  const hover = useStore((s) => s.hover);

  // Highlight only files near the viewport (work happens in a Web Worker).
  useEffect(() => {
    if (near || !ref.current) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), { rootMargin: "800px 0px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near) return;
    let alive = true;
    tokenize(file.text, file.language).then((t) => alive && setTokens(t));
    return () => {
      alive = false;
    };
  }, [file.text, file.language, near]);

  // Line offsets of each segment inside file.text.
  const offsets = useMemo(() => {
    const out: number[] = [];
    let n = 0;
    for (const seg of file.segments) {
      out.push(n);
      n += seg.text.split("\n").length;
    }
    return out;
  }, [file.segments]);

  const hovered = nodes.find((n) => n.id === hoverId);
  const pct = Math.min(100, (file.kept_tokens / Math.max(1, file.file_tokens)) * 100);

  const symbolAt = (line: number | null): string | null => {
    if (line === null) return null;
    let best: SliceNode | null = null;
    for (const n of nodes) {
      if (n.start_line <= line && line <= n.end_line && (!best || n.end_line - n.start_line < best.end_line - best.start_line)) best = n;
    }
    return best?.id ?? null;
  };

  return (
    <motion.section
      ref={ref}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30, delay: Math.min(index, 8) * 0.035 }}
      className="mb-3 overflow-hidden rounded-xl border border-line/80 bg-[rgb(var(--code-bg))] [content-visibility:auto]"
      data-file={file.path}
      onMouseLeave={() => hover(null)}
    >
      <header className="sticky top-0 z-10 flex items-center gap-2 border-b border-line/70 bg-panel/90 px-3 py-2 backdrop-blur">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: LANG_DOT[file.language] ?? "rgb(var(--faint))" }} />
        <span className="min-w-0 shrink truncate font-mono text-[12px]" title={file.path}>
          <span className="text-faint">{dirname(file.path)}</span>
          <span className="font-semibold text-fg">{basename(file.path)}</span>
        </span>
        <span className="ml-auto min-w-0 max-w-[38%] shrink-[2] truncate font-mono text-[10.5px] text-faint" title={`Kept lines ${rangesLabel(file.ranges)}`}>
          L{rangesLabel(file.ranges)}
        </span>
        <span
          className="relative h-1.5 w-12 shrink-0 overflow-hidden rounded-full bg-line"
          title={`${file.kept_tokens} of ${file.file_tokens} tokens kept`}
        >
          <motion.span
            className="absolute inset-y-0 left-0 rounded-full bg-callee"
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ type: "spring", stiffness: 120, damping: 20, delay: 0.15 }}
          />
        </span>
        <span className="w-[54px] shrink-0 text-right text-[10.5px] tabular-nums text-mute">{compact(file.kept_tokens)} tok</span>
      </header>
      <div className="code-font overflow-x-auto py-1.5">
        {file.segments.map((seg, si) =>
          seg.kind === "pruned" ? (
            <PrunedPill key={`p${seg.start}`} seg={seg} path={file.path} language={file.language} />
          ) : (
            <CodeLines
              key={`c${seg.start}`}
              seg={seg}
              tokens={tokens ? tokens.slice(offsets[si], offsets[si] + seg.lines.length) : null}
              hovered={hovered}
              onHoverLine={(line) => hover(symbolAt(line))}
            />
          ),
        )}
      </div>
    </motion.section>
  );
});

function CodeLines({
  seg,
  tokens,
  hovered,
  onHoverLine,
}: {
  seg: Segment;
  tokens: Tok[][] | null;
  hovered: SliceNode | undefined;
  onHoverLine: (line: number | null) => void;
}) {
  const texts = useMemo(() => seg.text.split("\n"), [seg.text]);
  return (
    <div>
      {texts.map((text, i) => {
        const n = seg.lines[i] ?? null;
        const note = n === null && /[▼] L\d+:/.test(text);
        const stub = n === null && !note && /⋯ \d+ lines?$/.test(text.trim());
        const inHover = hovered && n !== null && n >= hovered.start_line && n <= hovered.end_line;
        const crash = note && /crash site/.test(text);
        return (
          <div
            key={i}
            data-line={n ?? undefined}
            onMouseEnter={() => onHoverLine(n)}
            className={`group/line flex min-w-max transition-colors duration-100 ${
              inHover ? "bg-accent/[0.08]" : note ? (crash ? "bg-danger/[0.10]" : "bg-caller/[0.08]") : "hover:bg-fg/[0.03]"
            }`}
          >
            <span
              className={`sticky left-0 w-[52px] shrink-0 select-none bg-[rgb(var(--code-bg))] pr-3 text-right tabular-nums ${
                inHover ? "text-accent" : "text-faint/70"
              } ${note ? (crash ? "!text-danger" : "!text-caller") : ""}`}
            >
              {n ?? (note ? "▸" : "")}
            </span>
            <span className={`shiki-line whitespace-pre pr-4 ${stub ? "italic opacity-60" : ""} ${note ? (crash ? "font-semibold text-danger" : "font-semibold text-caller") : ""}`}>
              {note || !tokens || !tokens[i]
                ? text || " "
                : tokens[i].length
                  ? tokens[i].map((t, j) => (
                      <span key={j} style={t.style as React.CSSProperties}>
                        {t.content}
                      </span>
                    ))
                  : " "}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PrunedPill({ seg, path, language }: { seg: Segment; path: string; language: string }) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Tok[][] | null>(null);
  const [loading, setLoading] = useState(false);
  const fileContent = useStore((s) => s.fileContent);
  const count = seg.end - seg.start + 1;

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !lines) {
      setLoading(true);
      const content = await fileContent(path);
      if (content) {
        const slice = content.text.split("\n").slice(seg.start - 1, seg.end).join("\n");
        setLines(await tokenize(slice, language));
      }
      setLoading(false);
    }
  };

  return (
    <div className="px-2 py-1">
      <motion.button
        onClick={toggle}
        whileTap={{ scale: 0.985 }}
        className={`group flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left font-sans text-[11.5px] transition-colors ${
          open ? "border-accent/40 bg-accent/[0.06]" : "border-dashed border-line bg-elev/50 hover:border-accent/40 hover:bg-elev"
        }`}
        data-testid="pruned-pill"
        aria-expanded={open}
      >
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={{ type: "spring", stiffness: 500, damping: 30 }} className="text-mute">
          <ChevronRight size={13} />
        </motion.span>
        <span className="font-medium text-mute group-hover:text-fg">
          {count} line{count === 1 ? "" : "s"} pruned
        </span>
        <span className="font-mono text-[10.5px] text-faint">
          L{seg.start}
          {count > 1 ? `–${seg.end}` : ""}
        </span>
        <span className="flex min-w-0 flex-1 gap-1 overflow-hidden">
          {seg.symbols.slice(0, 3).map((s) => (
            <span key={s} className="truncate rounded-md bg-panel px-1.5 py-px font-mono text-[10.5px] text-mute shadow-[0_0_0_1px_rgb(var(--line))]">
              {s}
            </span>
          ))}
          {seg.symbols.length > 3 && <span className="shrink-0 text-[10.5px] text-faint">+{seg.symbols.length - 3}</span>}
        </span>
        <span className="shrink-0 rounded-md bg-ok/10 px-1.5 py-px text-[10.5px] font-semibold tabular-nums text-ok">−{compact(seg.tokens)} tok</span>
      </motion.button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 260, damping: 32 }}
            className="overflow-hidden"
          >
            <div className="relative mt-1 overflow-x-auto rounded-lg border border-line/60 bg-elev/40 py-1 opacity-75">
              <div className="absolute inset-y-0 left-0 w-[3px] bg-[repeating-linear-gradient(180deg,rgb(var(--faint)/0.6)_0_4px,transparent_4px_8px)]" />
              {loading && <div className="px-4 py-2 text-[11px] text-mute">Loading…</div>}
              {lines?.map((toks, i) => (
                <div key={i} className="flex min-w-max">
                  <span className="w-[44px] shrink-0 select-none pr-3 text-right tabular-nums text-faint/60">{seg.start + i}</span>
                  <span className="shiki-line whitespace-pre pr-4">
                    {toks.length
                      ? toks.map((t, j) => (
                          <span key={j} style={t.style as React.CSSProperties}>
                            {t.content}
                          </span>
                        ))
                      : " "}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
