import { AnimatePresence, motion } from "framer-motion";
import { Bug, FileCode2, Search } from "lucide-react";
import { useStore } from "../lib/store";

/** Centered hint over the idle repository constellation. */
export function EmptyHero() {
  const targets = useStore((s) => s.targets);
  const overview = useStore((s) => s.overview);
  const submit = useStore((s) => s.submit);
  const setInput = useStore((s) => s.setInput);
  const examples = (overview?.nodes ?? [])
    .filter((n) => n.kind === "function" || n.kind === "method")
    .slice(0, 3);
  return (
    <AnimatePresence>
      {!targets && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97, filter: "blur(4px)" }}
          transition={{ type: "spring", stiffness: 200, damping: 26, delay: 0.2 }}
          className="pointer-events-none flex max-w-[680px] flex-col items-center rounded-3xl border border-line/60 bg-bg/70 px-10 py-8 text-center shadow-glass backdrop-blur-md"
        >
          <div className="text-balance text-[26px] font-semibold leading-tight tracking-tight">
            Send the model <span className="bg-gradient-to-r from-accent to-callee bg-clip-text text-transparent">only the code that matters</span>
          </div>
          <div className="mt-2 max-w-[520px] text-[13.5px] leading-relaxed text-mute">
            Name a function, point at a line, or paste a stack trace. ast-pack walks the call graph, pulls in the types it needs and prunes the rest.
          </div>
          <div className="mt-5 flex flex-wrap justify-center gap-2 text-[12px] text-mute">
            <Hint icon={Search} text="processPayment" />
            <Hint icon={FileCode2} text="src/app.py:42" />
            <Hint icon={Bug} text="Traceback (most recent call last)…" />
          </div>
          {examples.length > 0 && (
            <div className="pointer-events-auto mt-6 flex flex-wrap items-center justify-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.12em] text-faint">Try</span>
              {examples.map((n) => (
                <motion.button
                  key={n.id}
                  whileHover={{ y: -2 }}
                  whileTap={{ scale: 0.96 }}
                  onClick={() => {
                    const t = `${n.path}::${n.qualname}`;
                    setInput(t);
                    submit(t);
                  }}
                  className="glass rounded-full px-3 py-1.5 font-mono text-[12px] text-fg"
                >
                  {n.qualname}
                </motion.button>
              ))}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Hint({ icon: Icon, text }: { icon: typeof Search; text: string }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-line/80 bg-panel/60 px-3 py-1 font-mono backdrop-blur">
      <Icon size={12} />
      {text}
    </span>
  );
}
