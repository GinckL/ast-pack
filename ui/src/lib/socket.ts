import type { FileContent, OverviewGraph, PackParams, PackResult, RepoStats, SymbolInfo } from "./types";

export type ConnState = "connecting" | "open" | "closed";

type ServerEvent =
  | { type: "hello"; version: string; root: string; stats: RepoStats }
  | { type: "index_updated"; stats: RepoStats }
  | { type: "conn"; state: ConnState };

interface Pending {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
  slot?: string;
}

/**
 * WebSocket client with request ids, automatic reconnection and
 * latest-wins slots: a newer `pack` on the same channel (or a newer search)
 * resolves the older promise with `null`, mirroring the server, which only
 * computes the latest message per channel.
 */
export class ApiSocket {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private slots = new Map<string, number>();
  private listeners = new Set<(e: ServerEvent) => void>();
  private retry = 0;
  private closedByUser = false;
  state: ConnState = "connecting";

  constructor(private readonly url: string) {
    this.connect();
  }

  on(fn: (e: ServerEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(e: ServerEvent) {
    this.listeners.forEach((fn) => fn(e));
  }

  private setState(s: ConnState) {
    this.state = s;
    this.emit({ type: "conn", state: s });
  }

  private connect() {
    this.setState("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setState("open");
    };
    ws.onmessage = (ev) => this.onMessage(ev.data as string);
    ws.onclose = () => {
      this.ws = null;
      for (const [id, p] of this.pending) {
        p.reject(new Error("connection lost"));
        this.pending.delete(id);
      }
      this.slots.clear();
      this.setState("closed");
      if (!this.closedByUser) {
        const delay = Math.min(8000, 300 * 2 ** this.retry++);
        setTimeout(() => this.connect(), delay);
      }
    };
  }

  close() {
    this.closedByUser = true;
    this.ws?.close();
  }

  private onMessage(raw: string) {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const type = msg.type as string;
    if (type === "hello" || type === "index_updated") {
      this.emit(msg as unknown as ServerEvent);
      return;
    }
    const id = msg.id as number | undefined;
    if (id === undefined || id === null) return;
    const p = this.pending.get(id);
    if (!p) return;
    this.pending.delete(id);
    if (p.slot && this.slots.get(p.slot) === id) this.slots.delete(p.slot);
    if (type === "error") p.reject(new Error(String(msg.message ?? "error")));
    else if (type === "pack_result") p.resolve(msg.result);
    else if (type === "search_result") p.resolve(msg.results);
    else if (type === "file_result") p.resolve(msg.file);
    else if (type === "graph_result") p.resolve(msg.graph);
    else if (type === "stats_result") p.resolve(msg.stats);
    else p.resolve(msg);
  }

  private request<T>(payload: Record<string, unknown>, slot?: string): Promise<T | null> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("not connected"));
    const id = this.nextId++;
    if (slot) {
      const prev = this.slots.get(slot);
      if (prev !== undefined) {
        const old = this.pending.get(prev);
        this.pending.delete(prev);
        old?.resolve(null); // superseded
      }
      this.slots.set(slot, id);
    }
    return new Promise<T | null>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, slot });
      ws.send(JSON.stringify({ ...payload, id }));
    });
  }

  get open(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  pack(params: PackParams, channel: "main" | "prefetch" | "profile" = "main"): Promise<PackResult | null> {
    if (!this.open) return restPack(params);
    return this.request<PackResult>({ type: "pack", channel, params }, `pack:${channel}`);
  }

  search(q: string, limit = 9): Promise<SymbolInfo[] | null> {
    if (!this.open) return restJson<{ results: SymbolInfo[] }>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`).then((r) => r.results);
    return this.request<SymbolInfo[]>({ type: "search", q, limit }, "search");
  }

  file(path: string): Promise<FileContent | null> {
    if (!this.open) return restJson<FileContent>(`/api/file?path=${encodeURIComponent(path)}`);
    return this.request<FileContent>({ type: "file", path });
  }

  graph(limit = 320): Promise<OverviewGraph | null> {
    if (!this.open) return restJson<OverviewGraph>(`/api/graph?limit=${limit}`);
    return this.request<OverviewGraph>({ type: "graph", limit });
  }
}

async function restJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = await r.json();
  if (!r.ok && !(body && "nodes" in body)) throw new Error(body?.error?.message ?? r.statusText);
  return body as T;
}

function restPack(params: PackParams): Promise<PackResult> {
  return restJson<PackResult>("/api/pack", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
}

export function socketUrl(): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws`;
}
