import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef } from "react";
import { CodePane } from "./components/CodePane";
import { CommandBar } from "./components/CommandBar";
import { ControlDock } from "./components/ControlDock";
import { useCopyBundle } from "./components/CopyButton";
import { EmptyHero } from "./components/EmptyHero";
import { GraphCanvas } from "./components/GraphCanvas";
import { Legend } from "./components/Legend";
import { Shortcuts } from "./components/Shortcuts";
import { Toasts } from "./components/Toasts";
import { TokenCounter } from "./components/TokenCounter";
import { Brand, CornerButtons } from "./components/TopBar";
import { warmup } from "./lib/highlight";
import { useStore } from "./lib/store";

export default function App() {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const codeOpen = useStore((s) => s.codeOpen);
  const codeWidth = useStore((s) => s.codeWidth);
  const setCodeWidth = useStore((s) => s.setCodeWidth);
  const { copy, burst, tokens, disabled } = useCopyBundle();

  useEffect(() => warmup(), []);

  // ---------------------------------------------------------------- shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const st = useStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      const typing = e.target instanceof HTMLElement && (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT");
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        return;
      }
      if (mod && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        void copy();
        return;
      }
      if (st.shortcutsOpen && e.key === "Escape") {
        st.setShortcuts(false);
        return;
      }
      if (typing || mod || e.altKey) return;
      const { depth } = st.settings;
      switch (e.key) {
        case "/":
          e.preventDefault();
          inputRef.current?.focus();
          break;
        case "[":
          st.setDepth(depth - 1);
          break;
        case "]":
          st.setDepth(depth + 1);
          break;
        case "1":
          st.setSettings({ direction: "both" });
          break;
        case "2":
          st.setSettings({ direction: "callers" });
          break;
        case "3":
          st.setSettings({ direction: "callees" });
          break;
        case "0":
        case "4":
        case "5":
        case "6":
          st.setDepth(Number(e.key));
          break;
        case "c":
        case "C":
          void copy();
          break;
        case "\\":
          st.toggleCode();
          break;
        case "f":
        case "F":
          st.fit();
          break;
        case "t":
        case "T":
          st.toggleTheme();
          break;
        case "?":
          st.setShortcuts(true);
          break;
        case "Escape":
          if (st.selectedId) st.select(null, false);
          else if (st.targets) st.clear();
          break;
        default:
          return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [copy]);

  // ----------------------------------------------------------- split resizing
  const dragging = useRef(false);
  const onResizeStart = useCallback(
    (e: React.PointerEvent) => {
      dragging.current = true;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      document.body.style.cursor = "col-resize";
    },
    [],
  );
  const onResizeMove = useCallback(
    (e: React.PointerEvent) => {
      if (dragging.current) setCodeWidth(window.innerWidth - e.clientX);
    },
    [setCodeWidth],
  );
  const onResizeEnd = useCallback(() => {
    dragging.current = false;
    document.body.style.cursor = "";
  }, []);

  return (
    <div className="flex h-full w-full overflow-hidden bg-bg">
      {/* Graph stage */}
      <main className="relative min-w-0 flex-1">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(1200px_600px_at_50%_-10%,rgb(var(--accent)/0.10),transparent_60%)]" />
        <GraphCanvas />

        <div className="pointer-events-none absolute inset-0 z-10">
          <div className="absolute inset-x-4 top-4 flex items-start gap-3">
            <Brand />
            <div className="flex min-w-0 flex-1 justify-center">
              <div className="w-full max-w-[640px]">
                <CommandBar inputRef={inputRef} />
              </div>
            </div>
            <CornerButtons />
          </div>
          <div className="absolute right-4 top-[84px]">
            <TokenCounter />
          </div>
          <div className="absolute inset-0 grid place-items-center px-8">
            <EmptyHero />
          </div>
          <div className="absolute bottom-4 left-4">
            <Legend />
          </div>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
            <ControlDock />
          </div>
          <div className="absolute bottom-5 right-4 hidden text-[11px] text-faint xl:block">
            drag to pan · scroll to zoom · double-click a node to re-root · <kbd className="kbd">?</kbd>
          </div>
        </div>
      </main>

      {/* Code pane */}
      <AnimatePresence initial={false}>
        {codeOpen && (
          <motion.aside
            key="code"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: codeWidth, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={dragging.current ? { duration: 0 } : { type: "spring", stiffness: 320, damping: 36 }}
            className="relative z-20 h-full shrink-0 border-l border-line/80 bg-panel/95"
          >
            <div
              onPointerDown={onResizeStart}
              onPointerMove={onResizeMove}
              onPointerUp={onResizeEnd}
              className="group absolute -left-1.5 top-0 z-30 h-full w-3 cursor-col-resize"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize code pane"
            >
              <div className="mx-auto h-full w-px bg-transparent transition-colors group-hover:bg-accent/70" />
            </div>
            <div className="h-full overflow-hidden" style={{ width: codeWidth }}>
              <CodePane copy={{ burst, onCopy: () => void copy(), tokens, disabled }} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      <Toasts />
      <Shortcuts />
    </div>
  );
}

