// Mirrors schema.json (the --json / API contract of the Python backend).

export type Role = "seed" | "callee" | "caller" | "type" | "value" | "container";
export type Mode = "full" | "outline" | "header";
export type Direction = "both" | "callers" | "callees";
export type Format = "markdown" | "xml" | "plain";

export interface SymbolInfo {
  id: string;
  name: string;
  qualname: string;
  kind: string;
  language: string;
  path: string;
  start_line: number;
  end_line: number;
  signature: string;
  tokens: number;
  score?: number;
  degree?: number;
}

export interface SliceNode extends SymbolInfo {
  hop: number;
  role: Role;
  mode: Mode;
  via: string | null;
  via_kind: string | null;
  confidence: number;
  truncated_neighbors: number;
}

export interface Edge {
  source: string;
  target: string;
  kind: "call" | "type" | "value";
  confidence: number;
  line?: number;
}

export interface Segment {
  kind: "code" | "pruned";
  start: number;
  end: number;
  text: string;
  symbols: string[];
  tokens: number;
  lines: (number | null)[];
}

export interface FileRender {
  path: string;
  language: string;
  ranges: [number, number][];
  symbols: string[];
  file_tokens: number;
  file_lines: number;
  kept_tokens: number;
  segments: Segment[];
  text: string;
}

export interface Frame {
  path: string;
  line: number;
  function: string | null;
  repo_path: string | null;
  symbol: string | null;
}

export interface PackStats {
  symbols: number;
  files: number;
  bundle_tokens: number;
  repo_tokens: number;
  touched_file_tokens: number;
  saved_pct: number;
  saved_vs_files_pct: number;
  tokenizer: string;
  tokenizer_exact: boolean;
  elapsed_ms: number;
  index_generation?: number;
}

export interface DepthPoint {
  depth: number;
  symbols: number;
  files: number;
  tokens: number;
}

export interface PackResult {
  ok: boolean;
  query: {
    targets: string[];
    kind: "symbol" | "file_line" | "file" | "trace" | "mixed";
    depth: number;
    direction: Direction;
    max_tokens: number | null;
    format: Format;
  };
  seeds: string[];
  stats: PackStats;
  nodes: SliceNode[];
  edges: Edge[];
  files: FileRender[];
  bundle: string;
  dropped: string[];
  warnings: string[];
  suggestions: string[];
  trace: null | {
    language: string;
    error: string | null;
    crash_site: Frame | null;
    frames: Frame[];
  };
  depth_profile: DepthPoint[];
}

export interface RepoStats {
  root: string;
  files: number;
  symbols: number;
  edges: number;
  tokens: number;
  lines: number;
  tokenizer: string;
  tokenizer_exact: boolean;
  languages: Record<string, { files: number; symbols: number; tokens: number; lines: number }>;
  generation: number;
}

export interface OverviewGraph {
  nodes: (SymbolInfo & { degree: number })[];
  edges: Edge[];
  total_symbols: number;
  total_edges: number;
}

export interface FileContent {
  path: string;
  language: string;
  lines: number;
  tokens: number;
  text: string;
}

export interface PackParams {
  targets: string[];
  depth: number;
  direction: Direction;
  max_tokens: number | null;
  format: Format;
  include_types: boolean;
  include_tests: boolean;
  strip_comments: boolean;
  min_confidence: number;
  prompt: string | null;
  depth_profile: boolean;
}
