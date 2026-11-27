# Rules for every agent

You are one of several Claude Code agents building NarcoPolo, each working on one module. You coordinate only through GitHub issues, pull requests and stage files — never by editing another module's files.

## Before you start

1. Your human starts you with `NARCO_MODULE=P<n>` set (P1 … P7). Without it, the guard hook blocks every edit.
2. Read, in order: `docs/shared.md` (once per session), then **only** your own spec `docs/specs/P<n>.md`. Do not read `docs/blueprint.md`, other modules' specs or other modules' code unless an issue tells you to — this is the main way we save tokens.
3. Take exactly one GitHub issue. One issue per session; clear context before the next.

## Hard rules (breaking any is a failed task, even if tests pass)

- Touch only your module's folders (listed in `.github/owners.json`) plus `STATUS.md` and `DECISIONS.md`. Never edit `core/` unless you are P1.
- Read only the stage files listed as your inputs. Never read `raw/` unless you are P1 (validation only), P3 or P4.
- Never invent a number, threshold, dataset name or API parameter. If the spec doesn't give it: add a config key with `TODO(P<n>)`, open an issue labelled `question`, and carry on with the simulator.
- Never store an unobserved cell as zero (Design principle 4).
- Never fit a model on data later than the training cut-off (principle 6). Every fit takes a `core.Split`.
- Never output a vessel name, MMSI, IMO number, call sign or a person's name anywhere.
- Every function gets a test against the simulator before it touches real data.
- Where `docs/shared.md`'s "Review passes and fixes" table or the "Issues found" table differs from a module spec, the table wins.
- All code is written during the hackathon weekend (fresh-code rule). Never paste in code from before Friday 27 November, including the old prototype dashboard.
- Secrets live only in environment variables or GitHub secrets. Never read `.env`; never print a token.
- **Never list yourself as a contributor.** Commits and PRs are credited to your human only: no `Co-Authored-By`, "Generated with Claude Code", session links or any other AI attribution in commit messages, PR descriptions or code. Commit with your human's own GitHub identity (their GitHub username and their GitHub email or `<id>+<username>@users.noreply.github.com`); never set or change `git config user.*` yourself. CI rejects commits authored by or crediting an AI.
- **Show which agent did what.** Start every commit subject and PR title with your module tag, e.g. `[P4] add CFAR background ring`. The git hook adds it automatically on `mod/p<n>/…` branches; CI rejects module-branch commits without it. Together with the human's GitHub name, the tag tells the team whose agent made each change.

## Work loop

1. `scripts/new_task.sh P<n> <issue-number>` creates a worktree on branch `mod/p<n>/<issue>` from `integration`. Work only there.
2. Write the test first, against the simulator; then the code.
3. Run `make test` (ruff, type checker, tach, pytest). Keep output quiet: `uv run pytest -q --tb=short`.
4. Commit in small steps. Push your branch only: `git push -u origin mod/p<n>/<issue>`. Never push to `main` or `integration`.
5. Open a PR into `integration` with the template filled in: what changed, which tests, which warnings from your spec you checked and how.
6. CI runs. Fix what they find. A human merges `integration` into `main` at checkpoints.
7. Update your module's line in `STATUS.md`.

## Stop and escalate

- Three failed CI fix attempts on the same issue: stop, label it `blocked`, write what you tried and the exact error, and wait for a human.
- Need a change in another module or in `core`? Open an issue on that module (label `module:P<m>`). Never edit it yourself.
- Discussion between agents happens only in issue comments, at most 3 rounds per thread; then a human decides and records it in `DECISIONS.md`.
- Passing lint, types and tests does not mean the statistics are right. Every PR touching a formula must name the simulator test that recovers a known answer with it.

## Contract changes (schemas, stage files, config keys other modules read)

After Friday 22:00 contracts are frozen. A change needs: an issue labelled `contract` → approval in comments from P1 and every affected owner → one PR (by P1) changing `core/schemas` and the docs together → everyone rebases.

## Overnight runs (during the event only)

Only issues labelled `overnight-ok`: well specified, simulator-tested, inside one module. Never overnight: contract changes, threshold tuning on real data, anything in `export/` or the pitch. A human reviews every overnight merge before 09:00. Stop at the token budget your human set, not at "done".

## Language rule for any output

Say "unusual", "worth checking" or "consistent with a drop-off". Never say "smuggling detected".
