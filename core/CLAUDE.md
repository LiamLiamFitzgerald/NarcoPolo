# core/ — owned by P1 (Core, simulator, validation, CI)

Your spec: `docs/specs/P1.md`. Shared context: `docs/shared.md`. Rules: `AGENTS.md`.

- Only P1 edits this folder and sim/, validate/.
- Public functions are exactly those listed for this folder in the spec's pseudo-codebase block; keep their names and signatures. Everything else is private (leading underscore).
- Tests live in `core/tests/` and run on the simulator first.
- If you need something from another module, open an issue labelled with its module; never edit its files.
