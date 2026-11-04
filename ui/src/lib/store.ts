import { create } from "zustand";
import { ApiSocket, socketUrl, type ConnState } from "./socket";
import type { DepthPoint, Direction, FileContent, Format, OverviewGraph, PackParams, PackResult, RepoStats, Role } from "./types";

export const MAX_DEPTH = 6;

export interface Settings {
  depth: number;
  direction: Direction;
  maxTokens: number | null;
  format: Format;
  includeTypes: boolean;
  includeTests: boolean;
  stripComments: boolean;
  exactOnly: boolean;
  prompt: string;
}

export interface Toast {
  id: number;
  tone: "info" | "ok" | "warn" | "error";
  title: string;
  body?: string;
}

interface Focus {
  path: string;
  line: number;
  nonce: number;
}

interface State {
  conn: ConnState;
  version: string;
  repo: RepoStats | null;
  overview: OverviewGraph | null;

  input: string;
  targets: string[] | null;
  settings: Settings;
  result: PackResult | null;
  pending: boolean;
  error: { message: string; suggestions: string[] } | null;
  profile: DepthPoint[] | null;

  hoverId: string | null;
  hoverRole: Role | null;
  selectedId: string | null;
  focus: Focus | null;
  fitNonce: number;

  codeOpen: boolean;
  codeWidth: number;
  theme: "dark" | "light";
  shortcutsOpen: boolean;
  toasts: Toast[];
  recents: string[];

  setInput: (s: string) => void;
  submit: (target?: string) => void;
  setSettings: (patch: Partial<Settings>) => void;
  setDepth: (d: number) => void;
  hover: (id: string | null) => void;
  hoverRoleSet: (r: Role | null) => void;
  select: (id: string | null, focusCode?: boolean) => void;
  focusLine: (path: string, line: number) => void;
  fit: () => void;
  toggleCode: (open?: boolean) => void;
  setCodeWidth: (w: number) => void;
  toggleTheme: () => void;
  setShortcuts: (open: boolean) => void;
  toast: (t: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
  clear: () => void;
  fileContent: (path: string) => Promise<FileContent | null>;
  reroot: (id: string) => void;
}

const DEFAULT_SETTINGS: Settings = {
  depth: 2,
  direction: "both",
  maxTokens: null,
  format: "markdown",
  includeTypes: true,
  includeTests: false,
  stripComments: false,
  exactOnly: false,
  prompt: "",
};

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / quota: settings just won't persist */
  }
}

function loadRecents(): string[] {
  try {
    const raw = localStorage.getItem("ast-pack-recents");
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}

export const socket = new ApiSocket(socketUrl());

function toParams(targets: string[], s: Settings, depth = s.depth, profile = false): PackParams {
  return {
    targets,
    depth,
    direction: s.direction,
    max_tokens: s.maxTokens,
    format: s.format,
    include_types: s.includeTypes,
    include_tests: s.includeTests,
    strip_comments: s.stripComments,
    min_confidence: s.exactOnly ? 1 : 0.5,
    prompt: s.prompt.trim() ? s.prompt : null,
    depth_profile: profile,
  };
}

const keyOf = (p: PackParams) => JSON.stringify({ ...p, depth_profile: false });
const baseKeyOf = (p: PackParams) => JSON.stringify({ ...p, depth: 0, depth_profile: false, format: "", prompt: null });

// Results are immutable for a given index generation; cleared on re-index.
const cache = new Map<string, PackResult>();
const fileCache = new Map<string, Promise<FileContent | null>>();
let profileKey = "";
let toastId = 1;
let prefetchToken = 0;

export const useStore = create<State>((set, get) => {
  async function prefetchAround(params: PackParams) {
    const token = ++prefetchToken;
    for (const d of [params.depth + 1, params.depth - 1, params.depth + 2]) {
      if (d < 0 || d > MAX_DEPTH) continue;
      const p = { ...params, depth: d, depth_profile: false };
      const k = keyOf(p);
      if (cache.has(k)) continue;
      try {
        const res = await socket.pack(p, "prefetch");
        if (token !== prefetchToken) return;
        if (res && res.ok) cache.set(k, res);
      } catch {
        return;
      }
    }
  }

  async function loadProfile(params: PackParams, base: string) {
    // Bundle size at every depth, computed in the background so the first
    // result paints immediately; feeds the slider sparkline and the counter.
    profileKey = base;
    try {
      const res = await socket.pack({ ...params, depth_profile: true }, "profile");
      if (res && res.ok && profileKey === base) set({ profile: res.depth_profile });
    } catch {
      if (profileKey === base) profileKey = "";
    }
  }

  async function run(opts: { quiet?: boolean } = {}) {
    const { targets, settings } = get();
    if (!targets || !targets.length) return;
    const base = baseKeyOf(toParams(targets, settings));
    const needProfile = base !== profileKey;
    if (needProfile) set({ profile: null });
    const params = toParams(targets, settings, settings.depth, false);
    const key = keyOf(params);
    const hit = cache.get(key);
    if (hit) {
      set({ result: hit, pending: false, error: null });
      if (needProfile) void loadProfile(params, base);
      void prefetchAround(params);
      return;
    }
    set({ pending: true });
    try {
      const res = await socket.pack(params, "main");
      if (res === null) return; // superseded by a newer request
      const current = get();
      const stillCurrent = current.targets === targets && keyOf(toParams(targets, current.settings)) === key;
      if (res.ok) cache.set(key, res);
      if (!stillCurrent) return;
      if (!res.ok) {
        set({
          pending: false,
          result: null,
          error: { message: res.warnings.join("; ") || "Nothing matched", suggestions: res.suggestions ?? [] },
        });
        return;
      }
      set({ result: res, pending: false, error: null });
      if (needProfile) void loadProfile(params, base);
      if (res.warnings.length && !opts.quiet) {
        get().toast({ tone: "warn", title: "Heads up", body: res.warnings[0] });
      }
      void prefetchAround(params);
    } catch (e) {
      set({ pending: false });
      get().toast({ tone: "error", title: "Pack failed", body: (e as Error).message });
    }
  }

  socket.on((ev) => {
    if (ev.type === "conn") {
      set({ conn: ev.state });
      if (ev.state === "open" && !get().overview) {
        socket.graph(320).then((g) => g && set({ overview: g })).catch(() => undefined);
      }
    } else if (ev.type === "hello") {
      set({ version: ev.version, repo: ev.stats });
      if (get().targets) {
        cache.clear();
        profileKey = "";
        void run({ quiet: true });
      }
    } else if (ev.type === "index_updated") {
      cache.clear();
      fileCache.clear();
      profileKey = "";
      set({ repo: ev.stats });
      socket.graph(320).then((g) => g && set({ overview: g })).catch(() => undefined);
      get().toast({ tone: "info", title: "Re-indexed", body: `${ev.stats.files.toLocaleString()} files · generation ${ev.stats.generation}` });
      void run({ quiet: true });
    }
  });

  const theme = (document.documentElement.classList.contains("dark") ? "dark" : "light") as "dark" | "light";

  return {
    conn: socket.state,
    version: "",
    repo: null,
    overview: null,
    input: "",
    targets: null,
    settings: load("ast-pack-settings", DEFAULT_SETTINGS),
    result: null,
    pending: false,
    error: null,
    profile: null,
    hoverId: null,
    hoverRole: null,
    selectedId: null,
    focus: null,
    fitNonce: 0,
    codeOpen: true,
    codeWidth: load("ast-pack-layout", { codeWidth: 560 }).codeWidth,
    theme,
    shortcutsOpen: false,
    toasts: [],
    recents: loadRecents(),

    setInput: (input) => set({ input }),

    submit: (target) => {
      const text = (target ?? get().input).trim();
      if (!text) return;
      const targets = [text];
      const recents = [text.includes("\n") ? text.split("\n").find((l) => l.trim()) ?? text : text, ...get().recents.filter((r) => r !== text)]
        .filter((r) => r.length < 200)
        .slice(0, 8);
      save("ast-pack-recents", recents);
      set({ targets, input: target ?? get().input, error: null, selectedId: null, recents });
      profileKey = "";
      void run();
    },

    setSettings: (patch) => {
      const settings = { ...get().settings, ...patch };
      set({ settings });
      save("ast-pack-settings", { ...settings, prompt: "" });
      void run();
    },

    setDepth: (d) => {
      const depth = Math.max(0, Math.min(MAX_DEPTH, Math.round(d)));
      if (depth === get().settings.depth) return;
      get().setSettings({ depth });
    },

    hover: (hoverId) => {
      if (get().hoverId !== hoverId) set({ hoverId });
    },
    hoverRoleSet: (hoverRole) => set({ hoverRole }),

    select: (id, focusCode = true) => {
      set({ selectedId: id });
      if (id && focusCode) {
        const node = get().result?.nodes.find((n) => n.id === id);
        if (node) {
          set({ focus: { path: node.path, line: node.start_line, nonce: Date.now() }, codeOpen: true });
        }
      }
    },

    focusLine: (path, line) => set({ focus: { path, line, nonce: Date.now() }, codeOpen: true }),
    fit: () => set({ fitNonce: get().fitNonce + 1 }),
    toggleCode: (open) => set({ codeOpen: open ?? !get().codeOpen }),
    setCodeWidth: (w) => {
      const codeWidth = Math.max(360, Math.min(window.innerWidth - 320, Math.round(w)));
      set({ codeWidth });
      save("ast-pack-layout", { codeWidth });
    },
    toggleTheme: () => {
      const theme = get().theme === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", theme === "dark");
      try {
        localStorage.setItem("ast-pack-theme", theme);
      } catch {
        /* ignore */
      }
      set({ theme });
    },
    setShortcuts: (shortcutsOpen) => set({ shortcutsOpen }),

    toast: (t) => {
      const id = toastId++;
      set({ toasts: [...get().toasts.slice(-3), { ...t, id }] });
      setTimeout(() => get().dismiss(id), t.tone === "error" ? 6000 : 3800);
    },
    dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

    clear: () => {
      prefetchToken++;
      set({ targets: null, result: null, input: "", error: null, pending: false, selectedId: null, profile: null });
      profileKey = "";
    },

    fileContent: (path) => {
      let p = fileCache.get(path);
      if (!p) {
        p = socket.file(path).catch(() => null);
        fileCache.set(path, p);
      }
      return p;
    },

    reroot: (id) => {
      const node = get().result?.nodes.find((n) => n.id === id) ?? get().overview?.nodes.find((n) => n.id === id);
      if (!node) return;
      const target = `${node.path}::${node.qualname}`;
      set({ input: target });
      get().submit(target);
    },
  };
});

/** Nodes to draw for the current depth, before the exact result arrives. */
export function visibleResult(result: PackResult | null, depth: number): PackResult | null {
  if (!result) return null;
  if (result.query.depth <= depth) return result;
  const nodes = result.nodes.filter((n) => n.hop <= depth);
  const ids = new Set(nodes.map((n) => n.id));
  return { ...result, nodes, edges: result.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}
