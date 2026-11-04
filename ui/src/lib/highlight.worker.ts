/// <reference lib="webworker" />
import type { HighlighterCore, ThemedToken } from "shiki/core";

/**
 * Shiki runs here so grammar compilation and tokenisation never block the
 * main thread (the graph keeps animating at full frame rate).
 */
const LANGS: Record<string, () => Promise<unknown>> = {
  python: () => import("shiki/langs/python.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  go: () => import("shiki/langs/go.mjs"),
  rust: () => import("shiki/langs/rust.mjs"),
};
const GRAMMAR: Record<string, string> = { javascript: "tsx" };

let core: Promise<HighlighterCore> | null = null;
const loaded = new Map<string, Promise<void>>();

function highlighter(): Promise<HighlighterCore> {
  if (!core) {
    core = (async () => {
      const [{ createHighlighterCore }, { createJavaScriptRegexEngine }] = await Promise.all([
        import("shiki/core"),
        import("shiki/engine/javascript"),
      ]);
      return createHighlighterCore({
        themes: [import("shiki/themes/github-dark-default.mjs"), import("shiki/themes/github-light-default.mjs")],
        langs: [],
        engine: createJavaScriptRegexEngine({ forgiving: true }),
      });
    })();
  }
  return core;
}

async function ensureLang(h: HighlighterCore, lang: string): Promise<string> {
  const grammar = GRAMMAR[lang] ?? lang;
  if (!LANGS[grammar]) return "text";
  let p = loaded.get(grammar);
  if (!p) {
    p = LANGS[grammar]().then((mod) => h.loadLanguage((mod as { default: never }).default));
    loaded.set(grammar, p);
  }
  await p;
  return grammar;
}

type Tok = [content: string, light: string, dark: string];

function colors(t: ThemedToken): [string, string] {
  const s = t.htmlStyle;
  if (!s) return [t.color ?? "", t.color ?? ""];
  if (typeof s !== "string") return [s["--shiki-light"] ?? "", s["--shiki-dark"] ?? ""];
  const m: Record<string, string> = {};
  for (const part of s.split(";")) {
    const i = part.indexOf(":");
    if (i > 0) m[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return [m["--shiki-light"] ?? "", m["--shiki-dark"] ?? ""];
}

self.onmessage = async (ev: MessageEvent<{ id: number; code?: string; lang: string; warm?: boolean }>) => {
  const { id, code, lang, warm } = ev.data;
  try {
    const h = await highlighter();
    const grammar = await ensureLang(h, lang);
    if (warm || code === undefined) {
      self.postMessage({ id, lines: null });
      return;
    }
    let lines: Tok[][];
    if (grammar === "text") {
      lines = code.split("\n").map((l) => [[l, "", ""]]);
    } else {
      const res = h.codeToTokens(code, {
        lang: grammar,
        themes: { light: "github-light-default", dark: "github-dark-default" },
        defaultColor: false,
      });
      lines = res.tokens.map((line) => line.map((t) => [t.content, ...colors(t)] as Tok));
    }
    self.postMessage({ id, lines });
  } catch (e) {
    self.postMessage({ id, error: String(e) });
  }
};
