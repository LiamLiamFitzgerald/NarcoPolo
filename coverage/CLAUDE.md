# coverage/ — owned by P3 (Reference and coverage)

Your spec: `docs/specs/P3.md`. Shared context: `docs/shared.md`. Rules: `AGENTS.md`.

- Only P3 edits this folder and reference/.
- Public functions are exactly those listed for this folder in the spec's pseudo-codebase block; keep their names and signatures. Everything else is private (leading underscore).
- Tests live in `coverage/tests/` and run on the simulator first.
- If you need something from another module, open an issue labelled with its module; never edit its files.
