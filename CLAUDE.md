# NarcoPolo

@AGENTS.md

Your module is given by the `NARCO_MODULE` environment variable (P1 … P7). Your spec is `docs/specs/$NARCO_MODULE.md`; shared context is `docs/shared.md`. Folder ownership is in `.github/owners.json`.

Use the `ponytail` skill (level full) for every coding task, and `ponytail-review` to review your own diff before opening a PR. Where ponytail conflicts with AGENTS.md or your spec, AGENTS.md and the spec win: every function still gets a simulator test, and every threshold still lives in `config.yaml`.

Before reading code to answer "how does X work / what calls Y", query the code graph: `graphify query "<question>" --budget 1500` (or `graphify explain "<name>"`, `graphify path "<a>" "<b>"`). If `graphify-out/` is missing or stale, rebuild it with `/graphify . --update` — it graphs code only (`.graphifyignore` excludes docs, so it costs no tokens). Never run graphify on `docs/`.

Useful commands: `make test`, `make sim`, `uv run pytest -q --tb=short <path>`, `uv run tach report <module>/` (what a module imports and who uses it — cheaper than reading code).
