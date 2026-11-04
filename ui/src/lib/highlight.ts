/**
 * Syntax highlighting via Shiki in a Web Worker (see highlight.worker.ts).
 * Results are memoised by (language, code).
 */
export interface Tok {
  content: string;
  style: Record<string, string>;
}

type Wire = [string, string, string];

let worker: Worker | null = null;
let nextId = 1;
const waiting = new Map<number, { resolve: (v: Tok[][]) => void; code: string }>();
const cache = new Map<string, Promise<Tok[][]>>();

function plain(code: string): Tok[][] {
  return code.split("\n").map((l) => [{ content: l, style: {} }]);
}

function getWorker(): Worker | null {
  if (worker) return worker;
  try {
    worker = new Worker(new URL("./highlight.worker.ts", import.meta.url), { type: "module" });
  } catch {
    return null;
  }
  worker.onmessage = (ev: MessageEvent<{ id: number; lines: Wire[][] | null; error?: string }>) => {
    const w = waiting.get(ev.data.id);
    if (!w) return;
    waiting.delete(ev.data.id);
    if (!ev.data.lines) {
      w.resolve(plain(w.code));
      return;
    }
    w.resolve(
      ev.data.lines.map((line) =>
        line.map(([content, light, dark]): Tok => ({ content, style: light || dark ? { "--shiki-light": light, "--shiki-dark": dark } : {} })),
      ),
    );
  };
  worker.onerror = () => {
    for (const [, w] of waiting) w.resolve(plain(w.code));
    waiting.clear();
  };
  return worker;
}

function post(code: string | undefined, lang: string, warm = false): Promise<Tok[][]> {
  const w = getWorker();
  if (!w) return Promise.resolve(plain(code ?? ""));
  const id = nextId++;
  return new Promise((resolve) => {
    waiting.set(id, { resolve, code: code ?? "" });
    w.postMessage({ id, code, lang, warm });
  });
}

export function tokenize(code: string, lang: string): Promise<Tok[][]> {
  const key = lang + "\u0000" + code;
  let p = cache.get(key);
  if (!p) {
    p = post(code, lang);
    if (cache.size > 400) cache.clear();
    cache.set(key, p);
  }
  return p;
}

/** Load the engine and common grammars before the first result arrives. */
export function warmup(langs: string[] = ["python", "typescript", "tsx"]): void {
  for (const l of langs) void post(undefined, l, true);
}
