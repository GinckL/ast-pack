import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, CheckCircle2, Info, RefreshCw, X } from "lucide-react";
import { useStore } from "../lib/store";

const ICON = { info: RefreshCw, ok: CheckCircle2, warn: Info, error: AlertCircle };
const TONE = { info: "text-accent", ok: "text-ok", warn: "text-caller", error: "text-danger" };

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed left-5 top-[86px] z-50 flex w-[340px] flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const Icon = ICON[t.tone];
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, x: -30, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -20, scale: 0.96, transition: { duration: 0.15 } }}
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
              className="glass pointer-events-auto flex items-start gap-2.5 rounded-xl px-3 py-2.5"
              role="status"
            >
              <Icon size={15} className={`mt-0.5 shrink-0 ${TONE[t.tone]}`} />
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-semibold">{t.title}</div>
                {t.body && <div className="mt-0.5 break-words text-[11.5px] text-mute">{t.body}</div>}
              </div>
              <button onClick={() => dismiss(t.id)} className="text-faint hover:text-fg" aria-label="Dismiss">
                <X size={13} />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
