/** 12_100 -> "12.1k", 142_000 -> "142k", 1_003_297 -> "1.0M". */
export function compact(n: number): string {
  const a = Math.abs(n);
  if (a < 1000) return String(Math.round(n));
  if (a < 10_000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  if (a < 1_000_000) return (n / 1000).toFixed(a < 100_000 ? 1 : 0).replace(/\.0$/, "") + "k";
  return (n / 1_000_000).toFixed(1) + "M";
}

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

export function basename(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}

export function dirname(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? "" : path.slice(0, i + 1);
}

export function rangesLabel(ranges: [number, number][]): string {
  return ranges.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
}

/** Heuristic used only for the command bar's live hint; the backend decides. */
export function detectTrace(text: string): { language: string; frames: number } | null {
  const py = text.match(/File "[^"]+", line \d+/g);
  if (py) return { language: "Python", frames: py.length };
  const node = text.match(/^\s*at .+:\d+:\d+\)?\s*$/gm);
  if (node) return { language: "Node.js", frames: node.length };
  const go = text.match(/^\s+\S+\.go:\d+/gm);
  if (go) return { language: "Go", frames: go.length };
  if (/panicked at .+\.rs:\d+/.test(text)) {
    const rs = text.match(/\.rs:\d+/g);
    return { language: "Rust", frames: rs ? rs.length : 1 };
  }
  const generic = text.match(/[\w./-]+\.(py|ts|tsx|js|jsx|go|rs):\d+/g);
  if (generic && generic.length >= 2 && text.includes("\n")) return { language: "trace", frames: generic.length };
  return null;
}

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const modKey = isMac ? "⌘" : "Ctrl";
