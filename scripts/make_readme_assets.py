"""Generate the README graphics in docs/assets from real benchmark data.

    python scripts/make_readme_assets.py

* hero.svg            animated banner (CSS animations; GitHub renders them)
* savings-light.svg   tokens sent for one function, per benchmark repository
* savings-dark.svg    same chart stepped for GitHub's dark theme

The chart numbers are parsed from benchmarks/RESULTS.md (depth-1 rows), so
re-running the benchmark and this script keeps the README honest.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Helvetica, Arial, sans-serif"
MONO = "'SFMono-Regular', 'JetBrains Mono', Menlo, Consolas, monospace"


def compact(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 100_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    if n < 1_000_000:
        return f"{round(n / 1000)}k"
    return f"{n / 1_000_000:.1f}M"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ benchmark
def benchmark_rows(depth: int = 1) -> list[dict]:
    text = (ROOT / "benchmarks" / "RESULTS.md").read_text("utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(
            r"\|\s*(\S+) @ `(\w+)`\s*\|\s*(\w+)\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*\*\*([\d.]+)%\*\*",
            line,
        )
        if m and int(m.group(5)) == depth:
            rows.append(
                {
                    "repo": m.group(1),
                    "lang": m.group(3),
                    "entry": m.group(4),
                    "bundle": int(m.group(8).replace(",", "")),
                    "total": int(m.group(9).replace(",", "")),
                    "saved": float(m.group(10)),
                }
            )
    if not rows:
        raise SystemExit("no benchmark rows found in benchmarks/RESULTS.md")
    return rows


THEMES = {
    # Single series (validated: #2a78d6 on #ffffff, #3987e5 on #0d1117 pass all checks).
    "light": {"surface": "#ffffff", "track": "#eef0f4", "bar": "#2a78d6", "text1": "#1f2328", "text2": "#59636e", "text3": "#818b98", "rule": "#e6e8ec"},
    "dark": {"surface": "#0d1117", "track": "#1c222b", "bar": "#3987e5", "text1": "#f0f3f6", "text2": "#9198a1", "text3": "#6e7681", "rule": "#262c36"},
}


def savings_chart(theme: str) -> str:
    t = THEMES[theme]
    rows = benchmark_rows(1)
    W, top, row_h = 900, 92, 46
    H = top + row_h * len(rows) + 46
    x0, x1 = 268, 660  # track span
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-labelledby="t d">',
        "<title id=\"t\">Tokens ast-pack sends for one function, per repository</title>",
        "<desc id=\"d\">"
        + esc("; ".join(f"{r['repo']}: {r['bundle']:,} of {r['total']:,} tokens ({r['saved']}% saved)" for r in rows))
        + "</desc>",
        # Deliberately static: a chart must read correctly in renderers that
        # never run animations (GitHub mobile, link previews, print).
        "<style>",
        f"text{{font-family:{FONT};}} .mono{{font-family:{MONO};}}",
        "</style>",
        f'<rect width="{W}" height="{H}" rx="14" fill="{t["surface"]}"/>',
        f'<text x="28" y="40" font-size="19" font-weight="700" fill="{t["text1"]}">Tokens sent to the model for one function</text>',
        f'<text x="28" y="64" font-size="13" fill="{t["text2"]}">Blue bar = ast-pack bundle (depth 1) · grey track = the whole repository · exact cl100k_base counts</text>',
    ]
    for i, r in enumerate(rows):
        y = top + i * row_h
        share = r["bundle"] / r["total"]
        w = max(6.0, (x1 - x0) * share)
        out += [
            f'<text x="28" y="{y + 15}" font-size="14" font-weight="650" fill="{t["text1"]}">{esc(r["repo"])}</text>',
            f'<text x="28" y="{y + 32}" font-size="11.5" fill="{t["text3"]}">{esc(r["lang"])} · <tspan class="mono">{esc(r["entry"])}</tspan></text>',
            f'<rect x="{x0}" y="{y + 9}" width="{x1 - x0}" height="12" rx="6" fill="{t["track"]}"/>',
            f'<rect x="{x0}" y="{y + 9}" width="{w:.1f}" height="12" rx="6" fill="{t["bar"]}"/>',
            f'<text x="{x1 + 18}" y="{y + 20}" font-size="13" fill="{t["text2"]}">'
            f'<tspan fill="{t["text1"]}" font-weight="650">{compact(r["bundle"])}</tspan> of {compact(r["total"])}</text>',
            f'<text x="{W - 28}" y="{y + 20}" font-size="14" font-weight="700" text-anchor="end" fill="{t["text1"]}">−{r["saved"]:.1f}%</text>',
        ]
        if i < len(rows) - 1:
            out.append(f'<line x1="28" x2="{W - 28}" y1="{y + row_h - 4}" y2="{y + row_h - 4}" stroke="{t["rule"]}"/>')
    out.append(
        f'<text x="28" y="{H - 18}" font-size="11.5" fill="{t["text3"]}">Source: benchmarks/RESULTS.md · reproducible with python benchmarks/bench.py (pinned commits)</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


# ----------------------------------------------------------------------- hero
def hero() -> str:
    W, H = 1280, 440
    cx, cy = 958, 214
    seed = ("processPayment", 0, 0)
    nodes = [
        # (label, dx, dy, role, delay)
        ("validateCard", 150, -86, "callee", 0.55),
        ("charge", 168, 22, "callee", 0.65),
        ("luhnOk", 272, -128, "callee", 1.05),
        ("fee", 286, 70, "callee", 1.15),
        ("checkoutHandler", -168, -40, "caller", 0.6),
        ("retryWorker", -150, 84, "caller", 0.7),
        ("routes", -276, 16, "caller", 1.1),
        ("PaymentRequest", -40, 138, "type", 0.9),
        ("Receipt", 44, 140, "type", 0.95),
        ("MAX_AMOUNT", 40, -150, "value", 1.25),
        ("Card", -150, 168, "type", 1.3),
    ]
    edges = [
        (seed, "validateCard"), (seed, "charge"), ("validateCard", "luhnOk"), ("charge", "fee"),
        ("checkoutHandler", seed), ("retryWorker", seed), ("routes", "checkoutHandler"),
        (seed, "PaymentRequest"), (seed, "Receipt"), ("validateCard", "MAX_AMOUNT"), ("PaymentRequest", "Card"),
    ]
    color = {"seed": "#8b9bff", "callee": "#4fd1c5", "caller": "#f6ad55", "type": "#c491ff", "value": "#f472b6"}
    pos = {seed[0]: (cx, cy)}
    role = {seed[0]: "seed"}
    delay = {seed[0]: 0.25}
    for label, dx, dy, r, d in nodes:
        pos[label] = (cx + dx, cy + dy)
        role[label] = r
        delay[label] = d

    def key(x):
        return x[0] if isinstance(x, tuple) else x

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="ast-pack: send the model only the code that matters">',
        "<defs>",
        '<radialGradient id="g1" cx="18%" cy="0%" r="70%"><stop offset="0" stop-color="#5b6cff" stop-opacity=".35"/><stop offset="1" stop-color="#5b6cff" stop-opacity="0"/></radialGradient>',
        '<radialGradient id="g2" cx="85%" cy="100%" r="60%"><stop offset="0" stop-color="#2dd4bf" stop-opacity=".22"/><stop offset="1" stop-color="#2dd4bf" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="tg" x1="0" x2="1"><stop offset="0" stop-color="#9aa8ff"/><stop offset="1" stop-color="#5eead4"/></linearGradient>',
        '<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#ffffff" fill-opacity=".06"/></pattern>',
        '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>',
        "</defs>",
        "<style>",
        f"text{{font-family:{FONT};}} .mono{{font-family:{MONO};}}",
        # One 8 s loop for everything: pop in (staggered), hold, gently fade, repeat.
        "@keyframes pop{0%{transform:scale(0);opacity:0}7%{transform:scale(1.18);opacity:1}11%{transform:scale(1)}86%{transform:scale(1);opacity:1}96%,100%{transform:scale(.4);opacity:0}}",
        "@keyframes draw{0%,4%{stroke-dashoffset:var(--l);opacity:0}5%{opacity:1}16%{stroke-dashoffset:0}86%{opacity:1;stroke-dashoffset:0}96%,100%{opacity:0;stroke-dashoffset:0}}",
        "@keyframes flow{to{stroke-dashoffset:-56}}",
        "@keyframes ring{0%{transform:scale(1);opacity:.65}100%{transform:scale(2.4);opacity:0}}",
        "@keyframes meter{0%,10%{stroke-dashoffset:131.9}30%,100%{stroke-dashoffset:4.4}}",
        "@keyframes fadein{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}",
        ".n{transform-box:fill-box;transform-origin:center;animation:pop 8s cubic-bezier(.2,.9,.25,1.1) infinite both}",
        ".e{animation:draw 8s ease-out infinite both}",
        ".f{stroke-dasharray:3 11;animation:flow 1.1s linear infinite}",
        ".r{transform-box:fill-box;transform-origin:center;animation:ring 1.8s ease-out infinite}",
        ".m{animation:meter 8s cubic-bezier(.2,.8,.2,1) infinite}",
        ".in{animation:fadein .8s ease-out both}",
        "@media (prefers-reduced-motion:reduce){.n,.e,.f,.r,.m,.in{animation:none}}",
        "</style>",
        f'<rect width="{W}" height="{H}" rx="22" fill="#0b0d12"/>',
        f'<rect width="{W}" height="{H}" rx="22" fill="url(#dots)"/>',
        f'<rect width="{W}" height="{H}" rx="22" fill="url(#g1)"/>',
        f'<rect width="{W}" height="{H}" rx="22" fill="url(#g2)"/>',
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="21.5" fill="none" stroke="#ffffff" stroke-opacity=".08"/>',
    ]
    # Left: wordmark + tagline
    out += [
        '<g class="in">',
        '<rect x="64" y="64" width="300" height="28" rx="14" fill="#ffffff" fill-opacity=".06" stroke="#ffffff" stroke-opacity=".1"/>',
        '<circle cx="82" cy="78" r="4" fill="#4ade80"/>',
        '<text x="94" y="83" font-size="12.5" font-weight="600" fill="#c9cfdb" letter-spacing=".6">TREE-SITTER · CALL GRAPH · LLM CONTEXT</text>',
        '<text x="62" y="170" font-size="78" font-weight="800" fill="#f5f7fb" letter-spacing="-2.5">ast-pack</text>',
        '<text x="64" y="222" font-size="29" font-weight="700" fill="url(#tg)" letter-spacing="-.5">Send the model only the code that matters.</text>',
        '<text x="64" y="262" font-size="17" fill="#9aa3b5">Give it a function, a file:line or a stack trace. It walks the call graph,</text>',
        '<text x="64" y="286" font-size="17" fill="#9aa3b5">keeps the types it needs and prunes everything else.</text>',
        "</g>",
    ]
    chips = ["Python", "TypeScript", "Go", "Rust", "MCP", "--json", "Web UI"]
    x = 64
    for i, c in enumerate(chips):
        w = 18 + len(c) * 8.4
        out.append(
            f'<g class="in" style="animation-delay:{0.25 + i * 0.06:.2f}s"><rect x="{x}" y="320" width="{w:.0f}" height="30" rx="9" fill="#ffffff" fill-opacity=".05" stroke="#ffffff" stroke-opacity=".12"/>'
            f'<text x="{x + w / 2:.0f}" y="340" font-size="13" font-weight="600" fill="#d7dce6" text-anchor="middle">{esc(c)}</text></g>'
        )
        x += w + 8
    out.append('<text class="in" x="64" y="392" font-size="13" fill="#6b7385">by Azimxon Vaxobov · Ginckl</text>')

    # Right: animated slice graph
    for a, b in edges:
        (x1, y1), (x2, y2) = pos[key(a)], pos[key(b)]
        length = math.hypot(x2 - x1, y2 - y1)
        start = max(delay[key(a)], delay[key(b)]) - 0.15
        target_role = role[key(b)]
        c = color[target_role if target_role != "seed" else role[key(a)]]
        if target_role in ("type", "value"):
            # Type / constant references: dashed, no flow.
            out.append(
                f'<line class="e" style="--l:{length:.0f};animation-delay:{start:.2f}s" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{c}" stroke-opacity=".45" stroke-width="1.3" stroke-dasharray="5 5"/>'
            )
        else:
            # Calls: the line draws itself, then dashes flow source -> target.
            out.append(
                f'<line class="e" style="--l:{length:.0f};stroke-dasharray:{length:.0f};animation-delay:{start:.2f}s" '
                f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-opacity=".55" stroke-width="1.6"/>'
            )
            out.append(f'<line class="f" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-opacity=".9" stroke-width="2"/>')
    for label, (x, y) in pos.items():
        r = role[label]
        rad = 17 if r == "seed" else 9 if r in ("callee", "caller") else 8
        c = color[r]
        dl = delay[label]
        dash = ' stroke-dasharray="3 2.5"' if r == "type" else ""
        g = [f'<g class="n" style="animation-delay:{dl:.2f}s">']
        if r == "seed":
            g.append(f'<circle cx="{x}" cy="{y}" r="{rad + 10}" fill="{c}" fill-opacity=".35" filter="url(#glow)"/>')
            g.append(f'<circle class="r" cx="{x}" cy="{y}" r="{rad + 3}" fill="none" stroke="{c}" stroke-width="1.5"/>')
        g.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="{c}" fill-opacity=".18" stroke="{c}" stroke-width="1.8"{dash}/>')
        g.append(f'<circle cx="{x}" cy="{y}" r="{3.5 if r == "seed" else 2.2}" fill="{c}"/>')
        weight = 700 if r == "seed" else 500
        size = 14 if r == "seed" else 11.5
        fill = "#f5f7fb" if r == "seed" else "#aeb6c6"
        g.append(
            f'<text x="{x}" y="{y + rad + 17}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="middle" class="mono">{esc(label)}</text>'
        )
        g.append("</g>")
        out.append("".join(g))

    # Savings card (real numbers: honojs/hono, Hono.fetch, depth 2)
    kx, ky = 1036, 336
    out += [
        f'<g class="in" style="animation-delay:.4s"><rect x="{kx}" y="{ky}" width="200" height="72" rx="14" fill="#11141b" fill-opacity=".92" stroke="#ffffff" stroke-opacity=".1"/>',
        f'<circle cx="{kx + 36}" cy="{ky + 36}" r="21" fill="none" stroke="#262b38" stroke-width="4"/>',
        f'<circle class="m" cx="{kx + 36}" cy="{ky + 36}" r="21" fill="none" stroke="#7dd3c0" stroke-width="4" stroke-linecap="round" '
        f'stroke-dasharray="131.9" stroke-dashoffset="4.4" transform="rotate(-90 {kx + 36} {ky + 36})"/>',
        f'<text x="{kx + 66}" y="{ky + 34}" font-size="24" font-weight="800" fill="#9aa8ff">−96.7%</text>',
        f'<text x="{kx + 66}" y="{ky + 54}" font-size="11.5" fill="#9aa3b5"><tspan class="mono">753k → 25.2k</tspan> tokens</text>',
        "</g>",
        f'<text x="{kx + 100}" y="{ky + 90}" font-size="10.5" fill="#596173" text-anchor="middle">measured: honojs/hono · Hono.fetch · depth 2</text>',
    ]
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hero.svg").write_text(hero(), "utf-8")
    for theme in THEMES:
        (OUT / f"savings-{theme}.svg").write_text(savings_chart(theme), "utf-8")
    print(f"wrote {OUT}/hero.svg, savings-light.svg, savings-dark.svg")


if __name__ == "__main__":
    main()
