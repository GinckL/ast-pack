import { AnimatePresence, motion } from "framer-motion";
import { modKey } from "../lib/format";
import { useStore } from "../lib/store";
import { CreditCard } from "./Credit";

const GROUPS: { title: string; items: [string[], string][] }[] = [
  {
    title: "Command bar",
    items: [
      [[modKey, "K"], "Focus the command bar"],
      [["↵"], "Pack the highlighted symbol"],
      [[modKey, "↵"], "Pack the text exactly as typed"],
      [["⇥"], "Complete the highlighted name"],
      [["Esc"], "Close results / leave the bar"],
    ],
  },
  {
    title: "Slice",
    items: [
      [["["], "Decrease hop depth"],
      [["]"], "Increase hop depth"],
      [["0", "–", "6"], "Set hop depth"],
      [["1"], "Walk callers + callees"],
      [["2"], "Walk callers only"],
      [["3"], "Walk callees only"],
    ],
  },
  {
    title: "View",
    items: [
      [[modKey, "⇧", "C"], "Copy optimized prompt"],
      [["C"], "Copy optimized prompt"],
      [["\\"], "Toggle code pane"],
      [["F"], "Fit graph to screen"],
      [["T"], "Toggle light / dark"],
      [["Esc"], "Clear selection, then back to overview"],
      [["?"], "This help"],
    ],
  },
];

export function Shortcuts() {
  const open = useStore((s) => s.shortcutsOpen);
  const setShortcuts = useStore((s) => s.setShortcuts);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setShortcuts(false)}
        >
          <motion.div
            initial={{ scale: 0.94, y: 12, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.96, y: 8, opacity: 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
            className="glass w-[min(720px,calc(100vw-32px))] rounded-2xl p-5"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="Keyboard shortcuts"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="text-[15px] font-semibold">Keyboard shortcuts</div>
              <kbd className="kbd">Esc</kbd>
            </div>
            <div className="grid gap-5 sm:grid-cols-3">
              {GROUPS.map((g) => (
                <div key={g.title}>
                  <div className="mb-2 text-[10.5px] font-medium uppercase tracking-[0.12em] text-faint">{g.title}</div>
                  <div className="space-y-1.5">
                    {g.items.map(([keys, label]) => (
                      <div key={label + keys.join("")} className="flex items-center justify-between gap-3 text-[12px]">
                        <span className="text-mute">{label}</span>
                        <span className="flex shrink-0 gap-1">
                          {keys.map((k) => (
                            <kbd key={k} className="kbd">
                              {k}
                            </kbd>
                          ))}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <CreditCard />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
