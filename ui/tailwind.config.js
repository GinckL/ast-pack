/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        elev: "rgb(var(--elev) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        mute: "rgb(var(--mute) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        seed: "rgb(var(--seed) / <alpha-value>)",
        callee: "rgb(var(--callee) / <alpha-value>)",
        caller: "rgb(var(--caller) / <alpha-value>)",
        type: "rgb(var(--type) / <alpha-value>)",
        value: "rgb(var(--value) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glass: "0 1px 0 0 rgb(255 255 255 / 0.04) inset, 0 20px 50px -12px rgb(0 0 0 / 0.55)",
        pop: "0 12px 40px -8px rgb(0 0 0 / 0.5), 0 0 0 1px rgb(var(--line) / 0.9)",
      },
      keyframes: {
        shimmer: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(100%)" } },
        pulseRing: { "0%": { transform: "scale(0.9)", opacity: "0.7" }, "100%": { transform: "scale(1.8)", opacity: "0" } },
      },
      animation: {
        shimmer: "shimmer 1.6s ease-in-out infinite",
        pulseRing: "pulseRing 1.6s cubic-bezier(0.2, 0.6, 0.3, 1) infinite",
      },
    },
  },
  plugins: [],
};
