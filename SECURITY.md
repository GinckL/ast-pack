# Security policy

## Supported versions

Security fixes are released for the latest minor version of ast-pack.

## Reporting a vulnerability

Please report privately, not in a public issue:

- GitHub: **Security → Report a vulnerability** on this repository (private advisory), or
- Telegram: [@A_Vakhobov](https://t.me/A_Vakhobov) (Azimxon Vaxobov, maintainer)

Include the version, how to reproduce, and the impact. You will get a reply within a few days.

## What ast-pack does with your code

- The CLI, library and MCP server read your repository locally and write a cache of parse results to `~/.cache/ast-pack` (override with `AST_PACK_CACHE_DIR`, disable with `--no-cache`). Nothing is uploaded anywhere.
- `tiktoken` may download its tokenizer vocabulary once; no repository content is sent.
- `ast-pack serve` / `--ui` binds to `127.0.0.1` by default and exposes repository source code to that address. It rejects requests whose `Host` is not local (DNS-rebinding protection) and browser requests or WebSocket connections from other origins. Binding to `0.0.0.0` prints a warning because it exposes the code to your network.
- The file endpoint only serves files that are part of the index; paths outside the repository are rejected.
