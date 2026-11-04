import type { Role } from "./types";

/** Reads the CSS colour tokens so the canvas follows the active theme. */
export interface Palette {
  bg: string;
  fg: string;
  mute: string;
  faint: string;
  line: string;
  grid: string;
  panel: string;
  danger: string;
  role: Record<Role | "idle", string>;
  rgb: Record<Role | "idle" | "danger" | "fg" | "line", [number, number, number]>;
}

function triplet(name: string): [number, number, number] {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parts = raw.split(/\s+/).map(Number);
  return parts.length === 3 && parts.every((n) => !Number.isNaN(n)) ? (parts as [number, number, number]) : [128, 128, 128];
}

const css = (t: [number, number, number]) => `rgb(${t[0]}, ${t[1]}, ${t[2]})`;

export function readPalette(): Palette {
  const seed = triplet("--seed");
  const callee = triplet("--callee");
  const caller = triplet("--caller");
  const type = triplet("--type");
  const value = triplet("--value");
  const faint = triplet("--faint");
  const fg = triplet("--fg");
  const line = triplet("--line");
  const danger = triplet("--danger");
  return {
    bg: css(triplet("--bg")),
    fg: css(fg),
    mute: css(triplet("--mute")),
    faint: css(faint),
    line: css(line),
    grid: css(triplet("--grid")),
    panel: css(triplet("--panel")),
    danger: css(danger),
    role: {
      seed: css(seed),
      callee: css(callee),
      caller: css(caller),
      type: css(type),
      value: css(value),
      container: css(faint),
      idle: css(faint),
    },
    rgb: { seed, callee, caller, type, value, container: faint, idle: faint, danger, fg, line },
  };
}

export const rgba = (t: [number, number, number], a: number) => `rgba(${t[0]}, ${t[1]}, ${t[2]}, ${a})`;

export const ROLE_LABEL: Record<Role, string> = {
  seed: "Entry",
  callee: "Callee",
  caller: "Caller",
  type: "Type",
  value: "Constant",
  container: "Container",
};

export const KIND_GLYPH: Record<string, string> = {
  function: "ƒ",
  method: "ƒ",
  macro: "!",
  class: "C",
  struct: "S",
  interface: "I",
  trait: "T",
  enum: "E",
  type: "T",
  union: "U",
  const: "K",
  static: "K",
  variable: "v",
  module: "M",
  impl: "⌗",
  block: "▸",
};
