## What changes

## Why

## How I verified it

- [ ] `pytest -q`
- [ ] `python benchmarks/validity.py <repo>` (if rendering or extraction changed)
- [ ] `npm run build && node e2e/smoke.mjs` in `ui/` (if the UI changed; built files committed)
- [ ] `schema.json` updated (if `--json` output changed)
- [ ] `CHANGELOG.md` updated
