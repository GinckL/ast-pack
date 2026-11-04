import { motion } from "framer-motion";
import { Keyboard, Moon, PanelRightOpen, Sun } from "lucide-react";
import { compact } from "../lib/format";
import { useStore } from "../lib/store";

export function Brand() {
  const repo = useStore((s) => s.repo);
  const conn = useStore((s) => s.conn);
  const clear = useStore((s) => s.clear);
  const name = repo?.root.split(/[\\/]/).filter(Boolean).pop() ?? "…";
  const dot = conn === "open" ? "bg-ok" : conn === "connecting" ? "bg-caller" : "bg-danger";
  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 28 }}
      className="glass pointer-events-auto flex h-[52px] shrink-0 items-center gap-3 rounded-2xl pl-2 pr-3.5"
    >
      <button onClick={clear} className="grid h-8 w-8 place-items-center rounded-xl bg-elev" title="Back to overview">
        <img src="/favicon.svg" alt="" className="h-6 w-6" />
      </button>
      <div className="min-w-0 leading-tight">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          ast-pack
          <span className="relative flex h-2 w-2" title={`Server ${conn}`}>
            {conn === "open" && <span className={`absolute inline-flex h-full w-full animate-pulseRing rounded-full ${dot}`} />}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${dot}`} />
          </span>
        </div>
        <div className="max-w-[200px] truncate text-[11px] text-mute" title={repo?.root}>
          {name}
          {repo && (
            <span className="text-faint" title={`${repo.files} files · ${repo.symbols} symbols · ${repo.edges} edges`}>
              {" "}
              · {compact(repo.files)} files · {compact(repo.symbols)} symbols
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export function CornerButtons() {
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);
  const setShortcuts = useStore((s) => s.setShortcuts);
  const codeOpen = useStore((s) => s.codeOpen);
  const toggleCode = useStore((s) => s.toggleCode);
  const btn = "grid h-9 w-9 place-items-center rounded-xl text-mute transition-colors hover:bg-elev hover:text-fg";
  return (
    <div className="glass pointer-events-auto flex h-[52px] shrink-0 items-center gap-0.5 rounded-2xl px-1.5">
      <button className={btn} onClick={() => setShortcuts(true)} title="Keyboard shortcuts (?)">
        <Keyboard size={16} />
      </button>
      <button className={btn} onClick={toggleTheme} title="Toggle theme">
        <motion.span key={theme} initial={{ rotate: -90, scale: 0.5 }} animate={{ rotate: 0, scale: 1 }} transition={{ type: "spring", stiffness: 400, damping: 18 }}>
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </motion.span>
      </button>
      {!codeOpen && (
        <button className={btn} onClick={() => toggleCode(true)} title="Show code (\)">
          <PanelRightOpen size={16} />
        </button>
      )}
    </div>
  );
}
