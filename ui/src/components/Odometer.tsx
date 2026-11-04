import { motion } from "framer-motion";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

function Digit({ d }: { d: number }) {
  return (
    <span className="relative inline-block h-[1em] w-[0.6em] overflow-hidden align-top leading-none" aria-hidden>
      <motion.span
        className="absolute inset-x-0 top-0 flex flex-col items-center"
        initial={false}
        animate={{ y: `${-d}em` }}
        transition={{ type: "spring", stiffness: 170, damping: 21, mass: 0.9 }}
      >
        {DIGITS.map((c) => (
          <span key={c} className="block h-[1em] leading-none">
            {c}
          </span>
        ))}
      </motion.span>
    </span>
  );
}

/** Rolling-digit number: each digit column springs to its new value. */
export function Odometer({ value, className = "" }: { value: string; className?: string }) {
  const chars = value.split("");
  return (
    <span className={`inline-flex items-start tabular-nums leading-none ${className}`} aria-label={value} role="text">
      {chars.map((c, i) => {
        const key = chars.length - i; // align from the right so units stay put
        return /\d/.test(c) ? (
          <Digit key={`d${key}`} d={Number(c)} />
        ) : (
          <motion.span key={`s${key}${c}`} layout="position" className="inline-block h-[1em] leading-none" aria-hidden>
            {c}
          </motion.span>
        );
      })}
    </span>
  );
}
