import { AnimatePresence, motion } from "framer-motion";
import { ROLE_LABEL } from "../lib/colors";
import { useStore, visibleResult } from "../lib/store";
import type { Role } from "../lib/types";

const ORDER: Role[] = ["seed", "callee", "caller", "type", "value"];

export function Legend() {
  const raw = useStore((s) => s.result);
  const depth = useStore((s) => s.settings.depth);
  const targets = useStore((s) => s.targets);
  const hoverRoleSet = useStore((s) => s.hoverRoleSet);
  const result = targets ? visibleResult(raw, depth) : null;
  const counts = new Map<Role, number>();
  for (const n of result?.nodes ?? []) counts.set(n.role, (counts.get(n.role) ?? 0) + 1);
  return (
    <AnimatePresence>
      {result && (
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -12 }}
          className="glass pointer-events-auto flex flex-col gap-0.5 rounded-2xl p-1.5"
          data-testid="legend"
        >
          {ORDER.map((role) => {
            const n = counts.get(role) ?? 0;
            return (
              <button
                key={role}
                onMouseEnter={() => n && hoverRoleSet(role)}
                onMouseLeave={() => hoverRoleSet(null)}
                className={`flex items-center gap-2 rounded-lg px-2 py-1 text-[11.5px] transition-colors hover:bg-elev ${n ? "" : "opacity-40"}`}
              >
                <span
                  className={`h-2.5 w-2.5 rounded-full border-[1.5px] ${role === "type" ? "border-dashed" : ""}`}
                  style={{ borderColor: `rgb(var(--${role}))`, background: `rgb(var(--${role}) / 0.25)` }}
                />
                <span className="text-mute">{ROLE_LABEL[role]}</span>
                <motion.span key={n} initial={{ y: -6, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="ml-auto pl-3 font-semibold tabular-nums">
                  {n}
                </motion.span>
              </button>
            );
          })}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
