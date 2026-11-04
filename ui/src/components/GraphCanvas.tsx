import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { KIND_GLYPH, ROLE_LABEL, readPalette, rgba, type Palette } from "../lib/colors";
import { compact } from "../lib/format";
import { useStore, visibleResult } from "../lib/store";
import type { Role } from "../lib/types";

type GRole = Role | "idle";

interface GNode extends SimulationNodeDatum {
  id: string;
  label: string;
  path: string;
  kind: string;
  role: GRole;
  hop: number;
  mode: string;
  tokens: number;
  r: number;
  s: number; // animated scale (spring)
  sv: number; // scale velocity
  target: number; // 1 = present, 0 = leaving
  delay: number; // timestamp before which the node stays hidden (stagger)
  crash: boolean;
  degree: number;
}

interface GLink extends SimulationLinkDatum<GNode> {
  key: string;
  kind: string;
  conf: number;
  progress: number;
}

interface DataNode {
  id: string;
  label: string;
  path: string;
  kind: string;
  role: GRole;
  hop: number;
  mode: string;
  tokens: number;
  via: string | null;
  crash: boolean;
  degree: number;
}

interface Tip {
  id: string;
  label: string;
  kind: string;
  role: GRole;
  hop: number;
  mode: string;
  path: string;
  lines: string;
  tokens: number;
  signature: string;
  via: string | null;
  confidence: number;
}

const radiusFor = (tokens: number, role: GRole) => {
  const base = 5 + Math.sqrt(Math.max(tokens, 1)) * 0.42;
  const r = Math.max(role === "idle" ? 3.5 : 7, Math.min(role === "idle" ? 10 : 22, base));
  return role === "seed" ? Math.max(r, 14) : r;
};

export function GraphCanvas() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  const rawResult = useStore((s) => s.result);
  const depth = useStore((s) => s.settings.depth);
  const overview = useStore((s) => s.overview);
  const targets = useStore((s) => s.targets);
  const theme = useStore((s) => s.theme);
  const fitNonce = useStore((s) => s.fitNonce);
  const result = useMemo(() => (targets ? visibleResult(rawResult, depth) : null), [rawResult, depth, targets]);

  const eng = useRef<Engine>({
    nodes: new Map<string, GNode>(),
    links: [],
    sim: forceSimulation<GNode>().stop(),
    cam: { x: 0, y: 0, k: 1 },
    userMoved: false,
    mode: "idle",
    queryKey: "",
    palette: null,
    w: 0,
    h: 0,
    dpr: 1,
    hover: null,
    drag: null,
  });

  // ------------------------------------------------------------ data → graph
  useEffect(() => {
    const e = eng.current;
    const now = performance.now();
    let data: DataNode[] = [];
    let edges: { source: string; target: string; kind: string; confidence: number }[] = [];
    const mode: "idle" | "slice" = result ? "slice" : "idle";
    const crashSymbol = result?.trace?.crash_site?.symbol ?? null;
    if (result) {
      data = result.nodes.map((n) => ({
        id: n.id,
        label: n.qualname,
        path: n.path,
        kind: n.kind,
        role: n.role,
        hop: n.hop,
        mode: n.mode,
        tokens: n.tokens,
        via: n.via,
        crash: n.id === crashSymbol,
        degree: 0,
      }));
      edges = result.edges;
    } else if (overview && !targets) {
      data = overview.nodes.map((n) => ({
        id: n.id,
        label: n.qualname,
        path: n.path,
        kind: n.kind,
        role: "idle" as const,
        hop: 0,
        mode: "full",
        tokens: n.tokens,
        via: null,
        crash: false,
        degree: n.degree,
      }));
      edges = overview.edges;
    }
    const queryKey = result ? result.seeds.join("|") + "|" + result.query.direction : mode;
    const newQuery = queryKey !== e.queryKey || mode !== e.mode;
    if (newQuery) e.userMoved = false;
    const incoming = new Set(data.map((d) => d.id));

    for (const d of data) {
      let n = e.nodes.get(d.id);
      const r = radiusFor(d.tokens, d.role);
      if (!n) {
        const anchor = d.via ? e.nodes.get(d.via) : undefined;
        const spread = mode === "idle" ? 260 : 40;
        const angle = Math.random() * Math.PI * 2;
        const x0 = anchor?.x ?? (d.role === "seed" ? 0 : Math.cos(angle) * spread * (mode === "idle" ? Math.random() : 1));
        const y0 = anchor?.y ?? (d.role === "seed" ? 0 : Math.sin(angle) * spread * (mode === "idle" ? Math.random() : 1));
        n = {
          ...d,
          r,
          x: x0 + (Math.random() - 0.5) * 24,
          y: y0 + (Math.random() - 0.5) * 24,
          s: 0,
          sv: 0,
          target: 1,
          delay: now + (mode === "slice" ? d.hop * 110 + (d.role === "type" || d.role === "value" ? 60 : 0) + Math.random() * 60 : Math.random() * 500),
        };
        e.nodes.set(d.id, n);
      } else {
        Object.assign(n, d, { r, target: 1 });
        if (n.s < 0.05) n.delay = now + d.hop * 80;
      }
    }
    for (const n of e.nodes.values()) {
      if (!incoming.has(n.id)) {
        n.target = 0;
        n.delay = now + (newQuery ? 0 : n.hop * 40);
      }
    }
    const old = new Map(e.links.map((l) => [l.key, l]));
    e.links = edges
      .filter((l) => incoming.has(l.source) && incoming.has(l.target) && l.source !== l.target)
      .map((l) => {
        const key = `${l.source}→${l.target}`;
        return {
          key,
          source: l.source,
          target: l.target,
          kind: l.kind,
          conf: l.confidence,
          progress: old.get(key)?.progress ?? 0,
        };
      });
    e.mode = mode;
    e.queryKey = queryKey;
    configureForces(e);
    e.sim.alpha(newQuery ? 1 : 0.55);
  }, [result, overview, targets]);

  useEffect(() => {
    eng.current.palette = readPalette();
  }, [theme]);

  useEffect(() => {
    eng.current.userMoved = false;
  }, [fitNonce]);

  // ------------------------------------------------------- render loop + input
  useEffect(() => {
    const canvas = canvasRef.current!;
    const wrap = wrapRef.current!;
    const ctx = canvas.getContext("2d")!;
    const e = eng.current;
    e.palette = readPalette();
    let raf = 0;
    let last = performance.now();

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      e.dpr = Math.min(window.devicePixelRatio || 1, 2);
      e.w = rect.width;
      e.h = rect.height;
      canvas.width = Math.round(rect.width * e.dpr);
      canvas.height = Math.round(rect.height * e.dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();

    const toWorld = (sx: number, sy: number) => ({
      x: (sx - e.w / 2) / e.cam.k + e.cam.x,
      y: (sy - e.h / 2 - VIEW_OFFSET_Y) / e.cam.k + e.cam.y,
    });
    const hit = (sx: number, sy: number): GNode | null => {
      const p = toWorld(sx, sy);
      let best: GNode | null = null;
      let bestD = Infinity;
      for (const n of e.nodes.values()) {
        if (n.target === 0 || n.s < 0.3) continue;
        const d = Math.hypot((n.x ?? 0) - p.x, (n.y ?? 0) - p.y);
        const reach = n.r * n.s + 6 / e.cam.k;
        if (d < reach && d < bestD) {
          best = n;
          bestD = d;
        }
      }
      return best;
    };

    const setHover = (n: GNode | null) => {
      if (e.hover === n) return;
      e.hover = n;
      canvas.style.cursor = n ? "pointer" : e.drag ? "grabbing" : "grab";
      useStore.getState().hover(n ? n.id : null);
    };

    const onDown = (ev: PointerEvent) => {
      canvas.setPointerCapture(ev.pointerId);
      const rect = canvas.getBoundingClientRect();
      const sx = ev.clientX - rect.left;
      const sy = ev.clientY - rect.top;
      const node = hit(sx, sy);
      e.drag = { node, sx, sy, cx: e.cam.x, cy: e.cam.y, moved: false };
      if (node) {
        node.fx = node.x;
        node.fy = node.y;
        e.sim.alphaTarget(0.25);
      } else {
        canvas.style.cursor = "grabbing";
      }
    };
    const onMove = (ev: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const sx = ev.clientX - rect.left;
      const sy = ev.clientY - rect.top;
      const d = e.drag;
      if (d) {
        if (Math.hypot(sx - d.sx, sy - d.sy) > 4) d.moved = true;
        if (d.node) {
          const p = toWorld(sx, sy);
          d.node.fx = p.x;
          d.node.fy = p.y;
        } else if (d.moved) {
          e.cam.x = d.cx - (sx - d.sx) / e.cam.k;
          e.cam.y = d.cy - (sy - d.sy) / e.cam.k;
          e.userMoved = true;
        }
        return;
      }
      setHover(hit(sx, sy));
    };
    const onUp = (ev: PointerEvent) => {
      const d = e.drag;
      e.drag = null;
      canvas.style.cursor = e.hover ? "pointer" : "grab";
      try {
        canvas.releasePointerCapture(ev.pointerId);
      } catch {
        /* already released */
      }
      if (!d) return;
      if (d.node) {
        d.node.fx = null;
        d.node.fy = null;
        e.sim.alphaTarget(0);
        if (!d.moved && e.mode === "slice") useStore.getState().select(d.node.id);
        if (!d.moved && e.mode === "idle") useStore.getState().reroot(d.node.id);
      } else if (!d.moved) {
        useStore.getState().select(null, false);
      }
    };
    const onLeave = () => {
      if (!e.drag) setHover(null);
    };
    const onDbl = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const node = hit(ev.clientX - rect.left, ev.clientY - rect.top);
      if (node && e.mode === "slice") useStore.getState().reroot(node.id);
      else if (!node) e.userMoved = false;
    };
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = ev.clientX - rect.left;
      const sy = ev.clientY - rect.top;
      const before = toWorld(sx, sy);
      const factor = Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0016));
      e.cam.k = Math.max(0.12, Math.min(3.5, e.cam.k * factor));
      e.cam.x = before.x - (sx - e.w / 2) / e.cam.k;
      e.cam.y = before.y - (sy - e.h / 2 - VIEW_OFFSET_Y) / e.cam.k;
      e.userMoved = true;
    };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("dblclick", onDbl);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.style.cursor = "grab";

    const frame = (now: number) => {
      const dt = Math.min(1 / 30, (now - last) / 1000);
      last = now;
      step(e, now, dt);
      draw(ctx, e, now);
      // Tooltip follows its node without re-rendering React.
      const tipEl = tipRef.current;
      const hn = e.hover;
      if (tipEl && hn) {
        const sx = (hn.x! - e.cam.x) * e.cam.k + e.w / 2;
        const sy = (hn.y! - e.cam.y) * e.cam.k + e.h / 2 + VIEW_OFFSET_Y;
        const flip = sx > e.w - 300;
        tipEl.style.transform = `translate(${flip ? sx - 16 - tipEl.offsetWidth : sx + hn.r * hn.s * e.cam.k + 14}px, ${sy - 24}px)`;
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("dblclick", onDbl);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, []);

  // Tooltip content (React) follows the store's hover id.
  const hoverId = useStore((s) => s.hoverId);
  useEffect(() => {
    const e = eng.current;
    if (!hoverId || !e.hover || e.hover.id !== hoverId) {
      setTip(null);
      return;
    }
    const n = rawResult?.nodes.find((x) => x.id === hoverId);
    const o = overview?.nodes.find((x) => x.id === hoverId);
    if (n) {
      setTip({
        id: n.id,
        label: n.qualname,
        kind: n.kind,
        role: n.role,
        hop: n.hop,
        mode: n.mode,
        path: n.path,
        lines: `${n.start_line}–${n.end_line}`,
        tokens: n.tokens,
        signature: n.signature,
        via: n.via ? rawResult?.nodes.find((x) => x.id === n.via)?.qualname ?? null : null,
        confidence: n.confidence,
      });
    } else if (o) {
      setTip({
        id: o.id,
        label: o.qualname,
        kind: o.kind,
        role: "idle",
        hop: 0,
        mode: "full",
        path: o.path,
        lines: `${o.start_line}–${o.end_line}`,
        tokens: o.tokens,
        signature: o.signature,
        via: null,
        confidence: 1,
      });
    }
  }, [hoverId, rawResult, overview]);

  return (
    <div ref={wrapRef} className="absolute inset-0 overflow-hidden" data-testid="graph">
      <canvas ref={canvasRef} className="block touch-none select-none" aria-label="Call graph of the context slice" />
      <div ref={tipRef} className="pointer-events-none absolute left-0 top-0 z-20 will-change-transform">
        <AnimatePresence>{tip && <TipCard key={tip.id} tip={tip} />}</AnimatePresence>
      </div>
    </div>
  );
}

// Vertical offset so the graph centres between the command bar and the dock.
const VIEW_OFFSET_Y = 10;

function TipCard({ tip }: { tip: Tip }) {
  const color = tip.role === "idle" ? "rgb(var(--faint))" : `rgb(var(--${tip.role === "container" ? "faint" : tip.role}))`;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.94, y: 4 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.08 } }}
      transition={{ type: "spring", stiffness: 520, damping: 34 }}
      className="glass w-[280px] origin-left rounded-xl px-3 py-2.5 text-[12px]"
    >
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 10px ${color}` }} />
        <span className="truncate font-mono text-[12.5px] font-semibold text-fg">{tip.label}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-mute">
        <span className="rounded bg-elev px-1.5 py-px">{tip.kind}</span>
        {tip.role !== "idle" && (
          <span className="rounded px-1.5 py-px" style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}>
            {ROLE_LABEL[tip.role as Role]}
            {(tip.role === "callee" || tip.role === "caller") && ` · hop ${tip.hop}`}
          </span>
        )}
        {tip.mode === "outline" && <span className="rounded bg-elev px-1.5 py-px">outline</span>}
        {tip.confidence < 1 && <span className="rounded bg-elev px-1.5 py-px">~{Math.round(tip.confidence * 100)}% match</span>}
        <span className="ml-auto tabular-nums">{compact(tip.tokens)} tok</span>
      </div>
      <div className="mt-1.5 truncate font-mono text-[11px] text-faint">
        {tip.path}:{tip.lines}
      </div>
      {tip.signature && (
        <div className="mt-1.5 line-clamp-2 break-all rounded-md bg-elev/70 px-2 py-1 font-mono text-[10.5px] leading-relaxed text-mute">
          {tip.signature}
        </div>
      )}
      {tip.via && <div className="mt-1.5 truncate text-[11px] text-faint">via {tip.via}</div>}
      <div className="mt-1.5 text-[10.5px] text-faint">
        {tip.role === "idle" ? "Click to pack this symbol" : "Click to jump to code · double-click to re-root"}
      </div>
    </motion.div>
  );
}

// --------------------------------------------------------------------- physics
interface Engine {
  nodes: Map<string, GNode>;
  links: GLink[];
  sim: Simulation<GNode, undefined>;
  cam: { x: number; y: number; k: number };
  userMoved: boolean;
  mode: "idle" | "slice";
  queryKey: string;
  palette: Palette | null;
  w: number;
  h: number;
  dpr: number;
  hover: GNode | null;
  drag: null | { node: GNode | null; sx: number; sy: number; cx: number; cy: number; moved: boolean };
}

const COL = 190;

function configureForces(e: Engine) {
  const idle = e.mode === "idle";
  const nodes = [...e.nodes.values()];
  e.sim.nodes(nodes);
  e.sim
    .alphaDecay(idle ? 0.012 : 0.022)
    .velocityDecay(idle ? 0.5 : 0.38)
    .force(
      "charge",
      forceManyBody<GNode>()
        .strength((d) => (d.target === 0 ? 0 : idle ? -26 - d.r * 3 : -170 - d.r * 14))
        .distanceMax(idle ? 260 : 720),
    )
    .force(
      "link",
      forceLink<GNode, GLink>(e.links)
        .id((d) => d.id)
        .distance((l) => (idle ? 34 : 64) + (l.source as GNode).r + (l.target as GNode).r + (l.kind === "call" ? 0 : 14))
        .strength((l) => (idle ? 0.12 : 0.55 * l.conf)),
    )
    .force("collide", forceCollide<GNode>((d) => d.r * Math.max(d.s, 0.4) + (idle ? 3 : 12)).strength(0.85))
    .force(
      "x",
      forceX<GNode>((d) => {
        if (idle) return 0;
        if (d.role === "callee") return d.hop * COL;
        if (d.role === "caller") return -d.hop * COL;
        return 0;
      }).strength((d) => (idle ? 0.035 : d.role === "seed" ? 0.3 : d.role === "callee" || d.role === "caller" ? 0.1 : 0.02)),
    )
    .force(
      "y",
      forceY<GNode>((d) => {
        if (idle) return 0;
        if (d.role === "type") return 150;
        if (d.role === "value") return 210;
        if (d.role === "container") return -150;
        return 0;
      }).strength((d) => (idle ? 0.035 : d.role === "seed" ? 0.3 : 0.06)),
    );
}

function step(e: Engine, now: number, dt: number) {
  let removed = false;
  for (const n of e.nodes.values()) {
    if (now < n.delay) continue;
    // Damped spring; slightly under-damped on entry for a pop, critically on exit.
    const k = n.target ? 210 : 320;
    const c = n.target ? 17 : 36;
    const a = k * (n.target - n.s) - c * n.sv;
    n.sv += a * dt;
    n.s += n.sv * dt;
    if (n.target === 0 && n.s < 0.02) {
      e.nodes.delete(n.id);
      removed = true;
    }
  }
  if (removed) {
    e.links = e.links.filter((l) => e.nodes.has((l.source as GNode).id) && e.nodes.has((l.target as GNode).id));
    configureForces(e);
  }
  for (const l of e.links) {
    const s = l.source as GNode;
    const t = l.target as GNode;
    if (s.s > 0.6 && t.s > 0.6) l.progress = Math.min(1, l.progress + dt * 2.6);
  }
  if (e.sim.alpha() > e.sim.alphaMin()) e.sim.tick();

  // Auto-fit camera until the user takes over.
  if (!e.userMoved && e.w > 0) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    let count = 0;
    for (const n of e.nodes.values()) {
      if (n.target === 0) continue;
      const r = n.r + 30;
      minX = Math.min(minX, n.x! - r);
      maxX = Math.max(maxX, n.x! + r);
      minY = Math.min(minY, n.y! - r);
      maxY = Math.max(maxY, n.y! + r);
      count++;
    }
    if (count) {
      const padX = 80;
      const padY = 250;
      const k = Math.max(0.18, Math.min(1.35, Math.min((e.w - padX) / (maxX - minX), (e.h - padY) / (maxY - minY))));
      const ease = 1 - Math.pow(0.001, dt);
      e.cam.x += ((minX + maxX) / 2 - e.cam.x) * ease;
      e.cam.y += ((minY + maxY) / 2 - e.cam.y) * ease;
      e.cam.k += (k - e.cam.k) * ease;
    }
  }
}

// --------------------------------------------------------------------- drawing
function draw(ctx: CanvasRenderingContext2D, e: Engine, now: number) {
  const p = e.palette;
  if (!p) return;
  const { w, h, dpr, cam } = e;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  // Dot grid (screen space, follows the camera).
  let spacing = 26 * cam.k;
  while (spacing < 14) spacing *= 2;
  const ox = ((w / 2 - cam.x * cam.k) % spacing + spacing) % spacing;
  const oy = ((h / 2 + VIEW_OFFSET_Y - cam.y * cam.k) % spacing + spacing) % spacing;
  ctx.fillStyle = rgba(p.rgb.fg, 0.07);
  for (let x = ox; x < w; x += spacing) {
    for (let y = oy; y < h; y += spacing) {
      ctx.fillRect(x - 0.6, y - 0.6, 1.2, 1.2);
    }
  }

  const st = useStore.getState();
  const hoverId = st.hoverId;
  const selectedId = st.selectedId;
  const hoverRole = st.hoverRole;
  let focusSet: Set<string> | null = null;
  if (hoverId && e.nodes.has(hoverId)) {
    focusSet = new Set([hoverId]);
    for (const l of e.links) {
      const s = (l.source as GNode).id;
      const t = (l.target as GNode).id;
      if (s === hoverId) focusSet.add(t);
      if (t === hoverId) focusSet.add(s);
    }
  } else if (hoverRole) {
    focusSet = new Set([...e.nodes.values()].filter((n) => n.role === hoverRole).map((n) => n.id));
  }
  const idle = e.mode === "idle";

  ctx.translate(w / 2, h / 2 + VIEW_OFFSET_Y);
  ctx.scale(cam.k, cam.k);
  ctx.translate(-cam.x, -cam.y);
  const px = 1 / cam.k;

  // Edges
  for (const l of e.links) {
    const s = l.source as GNode;
    const t = l.target as GNode;
    const a0 = Math.min(s.s, t.s);
    if (a0 <= 0.02 || l.progress <= 0) continue;
    const lit = !focusSet || (focusSet.has(s.id) && focusSet.has(t.id) && (s.id === hoverId || t.id === hoverId || !hoverId));
    const dim = lit ? 1 : 0.1;
    const sx = s.x!;
    const sy = s.y!;
    const tx = t.x!;
    const ty = t.y!;
    const dx = tx - sx;
    const dy = ty - sy;
    const len = Math.hypot(dx, dy) || 1;
    const bend = Math.min(40, len * 0.12);
    const cx = (sx + tx) / 2 - (dy / len) * bend;
    const cy = (sy + ty) / 2 + (dx / len) * bend;
    const color =
      idle ? p.rgb.fg : l.kind === "call" ? (t.role === "caller" || s.role === "caller" ? p.rgb.caller : p.rgb.callee) : l.kind === "type" ? p.rgb.type : p.rgb.value;
    const baseAlpha = idle ? 0.08 : l.kind === "call" ? 0.42 : 0.28;
    ctx.lineWidth = (idle ? 0.8 : l.kind === "call" ? 1.5 : 1.1) * px * (lit && focusSet ? 1.5 : 1);
    ctx.strokeStyle = rgba(color, baseAlpha * dim * Math.min(1, a0) * (0.5 + 0.5 * l.conf));
    const approx = len * 1.04;
    if (l.kind === "type") ctx.setLineDash([4 * px, 4 * px]);
    else if (l.kind === "value") ctx.setLineDash([1.2 * px, 3.5 * px]);
    else if (l.progress < 1) ctx.setLineDash([approx * l.progress, approx]);
    else ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.quadraticCurveTo(cx, cy, tx, ty);
    ctx.stroke();

    if (!idle && l.progress >= 1) {
      // Flowing energy along call edges (source → target).
      if (l.kind === "call" && lit) {
        ctx.setLineDash([2.5 * px, 11 * px]);
        ctx.lineDashOffset = -((now / 28) % 1000) * px;
        ctx.strokeStyle = rgba(color, 0.9 * dim * a0);
        ctx.lineWidth = 2 * px;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.quadraticCurveTo(cx, cy, tx, ty);
        ctx.stroke();
        ctx.lineDashOffset = 0;
      }
      // Arrowhead at the target's rim.
      ctx.setLineDash([]);
      const tdx = tx - cx;
      const tdy = ty - cy;
      const tl = Math.hypot(tdx, tdy) || 1;
      const ux = tdx / tl;
      const uy = tdy / tl;
      const rr = t.r * t.s + 3 * px;
      const ax = tx - ux * rr;
      const ay = ty - uy * rr;
      const as = 5 * px;
      ctx.fillStyle = rgba(color, Math.min(1, baseAlpha * 1.8) * dim * a0);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(ax - ux * as - uy * as * 0.6, ay - uy * as + ux * as * 0.6);
      ctx.lineTo(ax - ux * as + uy * as * 0.6, ay - uy * as - ux * as * 0.6);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.setLineDash([]);

  // Nodes
  const ordered = [...e.nodes.values()].sort((a, b) => (a.id === hoverId ? 1 : 0) - (b.id === hoverId ? 1 : 0) || a.r - b.r);
  for (const n of ordered) {
    const s = Math.max(0, n.s);
    if (s <= 0.01) continue;
    const r = n.r * s;
    const dim = focusSet && !focusSet.has(n.id) ? 0.16 : 1;
    const col = p.rgb[n.role] ?? p.rgb.idle;
    const x = n.x!;
    const y = n.y!;
    const isHover = n.id === hoverId;
    const isSel = n.id === selectedId;

    if (!idle && (n.role === "seed" || n.crash)) {
      const t = (now % 1800) / 1800;
      ctx.strokeStyle = rgba(n.crash ? p.rgb.danger : col, (1 - t) * 0.55 * dim);
      ctx.lineWidth = 1.5 * px;
      ctx.beginPath();
      ctx.arc(x, y, r + 4 * px + t * 22 * px, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (!idle && (n.role === "seed" || isHover || isSel)) {
      ctx.shadowColor = rgba(col, 0.75 * dim);
      ctx.shadowBlur = (isHover ? 26 : 18) * s;
    }
    ctx.fillStyle = rgba(col, (idle ? 0.35 : n.mode === "header" ? 0.06 : 0.17) * dim);
    ctx.strokeStyle = rgba(col, (idle ? 0.55 : 0.95) * dim);
    ctx.lineWidth = (idle ? 1 : isHover ? 2.2 : 1.6) * px;
    if (n.mode === "outline") ctx.setLineDash([3 * px, 2.4 * px]);
    ctx.beginPath();
    if (n.mode === "header") {
      const rr = r * 0.9;
      roundRect(ctx, x - rr, y - rr, rr * 2, rr * 2, rr * 0.35);
    } else {
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;

    if (!idle && n.mode === "full") {
      ctx.fillStyle = rgba(col, 0.9 * dim);
      ctx.beginPath();
      ctx.arc(x, y, Math.max(1.6 * px, r * 0.2), 0, Math.PI * 2);
      ctx.fill();
    }
    if (!idle && r * cam.k > 11) {
      const glyph = KIND_GLYPH[n.kind] ?? "·";
      ctx.fillStyle = rgba(p.rgb.fg, 0.85 * dim);
      ctx.font = `600 ${Math.max(7, r * 0.82)}px Inter, ui-sans-serif, system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(glyph, x + r * 0.42, y - r * 0.42);
    }
    if (isSel) {
      ctx.strokeStyle = rgba(p.rgb.fg, 0.9);
      ctx.lineWidth = 1.6 * px;
      ctx.beginPath();
      ctx.arc(x, y, r + 5 * px, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (n.crash && !idle) {
      ctx.strokeStyle = rgba(p.rgb.danger, 0.95);
      ctx.lineWidth = 2 * px;
      ctx.beginPath();
      ctx.arc(x, y, r + 2.5 * px, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  // Labels (constant screen size)
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (const n of ordered) {
    if (n.s < 0.6) continue;
    const isHover = n.id === hoverId;
    const dimmed = focusSet && !focusSet.has(n.id);
    const show =
      isHover ||
      n.id === selectedId ||
      (!idle && (n.role === "seed" || (!dimmed && cam.k > 0.62))) ||
      false;
    if (!show) continue;
    const fs = (n.role === "seed" ? 12.5 : 11) * px;
    ctx.font = `${n.role === "seed" || isHover ? 600 : 500} ${fs}px Inter, ui-sans-serif, system-ui`;
    const text = n.label.length > 34 && !isHover ? n.label.slice(0, 32) + "…" : n.label;
    const y = n.y! + n.r * n.s + 6 * px;
    const alpha = Math.min(1, (n.s - 0.6) / 0.4) * (dimmed ? 0.25 : 1);
    if (isHover || n.role === "seed") {
      const tw = ctx.measureText(text).width;
      ctx.fillStyle = p.panel.replace("rgb(", "rgba(").replace(")", `, ${0.82 * alpha})`);
      ctx.beginPath();
      roundRect(ctx, n.x! - tw / 2 - 6 * px, y - 2.5 * px, tw + 12 * px, fs + 6 * px, 6 * px);
      ctx.fill();
    }
    ctx.fillStyle = rgba(isHover || n.role === "seed" ? p.rgb.fg : p.rgb.fg, (isHover || n.role === "seed" ? 1 : idle ? 0.55 : 0.72) * alpha);
    ctx.fillText(text, n.x!, y);
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
