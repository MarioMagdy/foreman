# Worker launcher

**Status: built and tested** (`launcher.py`, stdlib Python; self-check `test_launcher.py` in the repo, not installed). Real
smoke run on 2026-10-11: 3 Step-5 jobs on 2 slots; the third queued until a slot freed; all three
wrote their files and handed back `STATUS: DONE`; 0 `database is locked`; the pool outlived the shell
that started it.

**Needs:** Windows, Python 3.10+, and the `opencode` CLI signed in (found on PATH, or set `FOREMAN_OPENCODE`). It
drives opencode workers only; on another OS or harness, start workers your own way and write the same events.

**Files a worker uses** (in its worktree's `_scratch/`; `delegation/prepare_worktree.py` sets them up, otherwise
put these three lines in every brief):
- `PROGRESS.md`: append one line after each step. The launcher reads its time as a heartbeat: no activity for
  max(2 x `--expect`, `--hang-min`) minutes marks the job hung.
- `MAILBOX.md`: read it after each step and follow any new line. `launcher.py soft <job>` appends the soft stop here.
- `HANDOFF.md`: on a soft stop, write what is done, what is left, how to continue and the test status, then end
  with the STATUS block.

Where it runs (Windows, opencode workers), the launcher is the only way a builder, reviewer or tester starts in a
track-mode run. It owns the
shared resources so managers never coordinate them by hand.

## Commands
`--coord` is the run's `_coord/` folder (or set `FOREMAN_COORD`). Paths to briefs may be relative to it.
```text
python <skill>/track-mode/launcher.py --coord <dir> start [--port 4300] [--slots 3] [--db <path>]   # orchestrator, at run start
launch submit --stage <id> --role builder|reviewer|tester --model <provider/model> --brief <path> \
              --workdir <worktree> --actor <manager id> [--expect <min>] [--critical] [--fix]   -> prints job id
                              (--fix: a fix round, logged as `fix_brief` instead of `brief`)
launch status <job>        -> queued | running | done | failed:<reason> | hung | quota | cancelled
launch wait <job>          -> blocks until final; prints the state and the report path
                              (run it in the background, or poll `status`: a shell tool call times out long before a 30-minute build)
launch cancel <job>
launch jobs [--actor <id>] -> one line per job
launch health              -> ok | DOWN, slots in use, queue length (exit 1 when DOWN)
launch stop                -> orchestrator, at run end: stops jobs, the server and the pool
```
(`launch` = `python <skill>/track-mode/launcher.py --coord <dir>`.)

## What it owns
- **One `opencode serve`** for the whole run, on a fixed port with a random per-run password (so
  no other local process can drive it). Every job attaches to it (`opencode run --attach … --auto
  --format json -f <brief>`): one process owns opencode's database, and an attached job is one
  process, not ~60. `--db` gives the run its own opencode database (`OPENCODE_DB`).
- **A slot pool** (`profile.workers.opencode_slots`, default 3, tested up to 5). FIFO, with
  `--critical` stages first. Client starts are staggered 2 s (Windows `0xC0000142`).
- **Health**: the server is checked every tick. If it fails 3 checks in a row, it is restarted. Its
  running jobs are re-queued once and then marked `failed:server`. If the pool itself was restarted,
  it re-queues the orphaned jobs once.
- **Answers**: when a job's client exits, the launcher reads the final assistant message from
  `GET /session/<id>/message` and saves it, with cost, tokens and seconds, to `reports/<job>.md`.
  The last `STATUS:` line becomes the hand-back summary.

## Files (one writer each)
| Path under `_coord/` | Writer |
|---|---|
| `launcher/queue/<job>.json` | `submit`, once (ids are `<stage>-<role>-<n>`, created exclusively so two managers never collide) |
| `launcher/cancel/<job>` | `cancel` |
| `launcher/jobs/<job>.json`, `launcher/daemon.json`, `launcher/server.log`, `launcher/logs/` | the pool |
| `events/launcher.jsonl`, `reports/<job>.md` | the pool |

## Events it writes (`events/launcher.jsonl`, `ts` in ISO-8601 UTC with `Z`)
| kind | actor → to | when |
|---|---|---|
| `brief` | `manager:<id>` → `<role>:<model>` | job queued (the hand-off) |
| `handback` | `<role>:<model>` → `manager:<id>` | client exited with an answer; carries `worker_status`, `cost`, `tokens`, `secs` |
| `hang` | `launcher` → `manager:<id>` | no session activity for `max(2 × --expect, 20 min)` |
| `quota` | `launcher` → `manager:<id>` | a usage-limit `ERROR` for that job's session in the server log, or in the session's error |
| `failed` | `launcher` → `manager:<id>` | non-zero exit with no answer, server death, cancel, stop |

Every line also carries `job` and `via: launcher`. Usage-limit messages have their URLs removed,
because they carry the account's workspace link.

On `hang` or `quota` the launcher aborts the session, kills the client and frees the slot. **Which
model runs it next is the manager's call**, following the profile's fallback chain.

## Not handled
- Two jobs editing one worktree: parallel stages need separate worktrees (the manager's job).
- Claude workers (e.g. a Sonnet fallback) are started by the manager as its harness file says (the Agent tool in
  Claude Code; a manager without one asks the orchestrator with a `staff_request`); the
  manager logs their `brief`/`handback` events itself.
- Runs on other machines or cloud sessions: local pool only; a `session`/`cloud`
  launcher is a second implementation of the same commands, written when the first remote run needs it.
