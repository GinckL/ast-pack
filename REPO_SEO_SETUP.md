# Repository setup checklist (discoverability)

For ast-pack by Azimxon Vaxobov (Ginckl).

Paste-ready values for GitHub settings and launch posts. Character counts were checked against GitHub's and Hacker News's limits.

## 1. GitHub "About" description (320 / 350 characters)

```text
Pack only the code an LLM needs: give ast-pack a function, file:line or stack trace and it walks the Tree-sitter call graph (callers, callees, types, constants) and prunes the rest into a valid, token-minimal prompt. Repomix alternative for ChatGPT, Claude, Cursor & AI agents. Python, TS/JS, Go, Rust. CLI, --json, MCP.
```

Website field: `https://pypi.org/project/ast-pack/` once published (until then, leave it empty or link the README).

## 2. GitHub topics (exactly 20; GitHub allows at most 20)

```text
llm llm-context context-packing prompt-engineering token-optimization tree-sitter ast call-graph static-analysis program-slicing code-context repomix-alternative stack-trace debugging mcp-server ai-coding-agent claude chatgpt cursor developer-tools
```

## 3. Launch titles

Hacker News (76 / 80 characters):

```text
Show HN: ast-pack – LLM context from a call-graph slice, not your whole repo
```

Reddit (r/LocalLLaMA, r/ChatGPTCoding, r/ClaudeAI, r/Python, r/programming — check each subreddit's self-promotion rules first):

```text
I built ast-pack: give it a function or stack trace, get only the code an LLM needs (87–98% fewer tokens than packing the repo)
```

First comment / post body should link `benchmarks/RESULTS.md` and state how to reproduce the numbers (`python benchmarks/bench.py`); reviewers and AI search engines both favour claims with a reproducible source.

## 4. Launch steps (do these once)

1. **Default branch `main`** — the links in `llms.txt` / `llms-full.txt` point to `main`.
2. **Social preview** — Settings → General → Social preview → upload `docs/assets/social-preview.png` (1280×640). This is the card shown when the repo link is shared on X, LinkedIn, Telegram or Slack.
3. **PyPI via trusted publishing** (no API token stored anywhere) so `pip install ast-pack` resolves; the name was unclaimed on 2026-11-04:
   - on pypi.org: *Your projects → Publishing → Add a pending publisher* with owner `ginckl`, repository `ast-pack`, workflow `release.yml`, environment `pypi`;
   - on GitHub: Settings → Environments → create `pypi`;
   - then `git tag v0.1.0 && git push origin v0.1.0`. `.github/workflows/release.yml` checks the tag matches `pyproject.toml`, builds, smoke-tests the wheel (including the bundled web UI), publishes to PyPI and creates the GitHub Release.
4. **After the first release** add a PyPI badge to the README badge row: `https://img.shields.io/pypi/v/ast-pack`.
5. **Enable** Discussions, private vulnerability reporting (Settings → Code security) and Dependabot alerts. GitHub shows "Cite this repository" automatically from `CITATION.cff`.

## 5. Indexing hygiene

- Keep `README.md`, `llms.txt`, `llms-full.txt` and `AGENT_GUIDE.md` on the default branch; regenerate `llms-full.txt` after doc changes with `python scripts/build_llms_full.py`.
- Enable Discussions and pin a "Benchmarks on your repo" thread; real user numbers are the strongest signal for both people and AI answer engines.
- Search engines and AI answer engines decide on their own schedule when to crawl; nothing guarantees indexing within a fixed time. Links from the launch posts, PyPI and awesome-lists (e.g. awesome-llm-tools, awesome-mcp-servers) are what get the repository crawled.
