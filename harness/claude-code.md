# Foreman in Claude Code

Read this when the session runs in Claude Code. `SKILL.md` holds the rules; this file says how to do its
harness-dependent steps with Claude Code's tools. Anything not covered here works as in `harness/generic.md`.

## The seven harness steps

| Action | In Claude Code |
|---|---|
| Start a worker or manager | The Agent tool (a subagent). Agent-tool subagents notify on their own when they finish, and survived every memory-pressure reap that killed background shell jobs. Workers routed to other models (opencode, codex, Gemini) still go through `track-mode/launcher.py` or those CLIs. |
| Wake on a handback | Arm a Monitor on `_coord/events/launcher.jsonl` filtered to `handback\|hang\|quota\|failed`. It lasts at most 30 min: re-arm it every time it ends, not only at check-ins, or handbacks go unseen until the next one. |
| Scheduled check-ins | CronCreate, every 30-60 min, created when the run starts and deleted at the end. It is the safety net behind the Monitor. Cron jobs live only as long as the session. |
| Show the owner the run | An Artifact: the live tracker, below. |
| Take the owner's answers | Comments on that Artifact, read with `ArtifactComments` (they also arrive as a message to this session). |
| Resume a manager, update the owner | A manager that ended its turn with `QUESTION <id>` is resumed by messaging that subagent (SendMessage) with the answer; if it is gone, start a new one from its track file. Owner updates are a short chat message, plus a republish of the tracker. |
| Name models | The Agent tool takes aliases (`sonnet`, `opus`, `haiku`): write the alias in the run sheet and say it is one. Other harnesses' models are version-suffixed and checked live. |

## The live tracker as an Artifact (track mode, and any run with `live.py`)

From the run folder, `python <skill>/track-mode/live.py build --coord _coord` writes `tracker.html` (titled "<project> Foreman", so each run's artifact
has its own name), `run.json`, `packet.html` and `packets/` into `_coord/live/`. Publish that `tracker.html` once
with `files: {"run.json": <built file>, "packet.html": <built file>}` plus each `packets/<gate id>.json`, and
`capabilities: {comments: {}}`. Republish with the new `run.json` when a stage changes state or finishes, when a
manager posts an update, and at every check-in.

**The owner answers on the page.** Every `question` event for the owner carries `qid`, `options` and `recommended`;
the page shows them with who raised the question and each hop it took. The owner's picks arrive as one comment.
Log one `answer` event per `qid` (actor `owner`), reply in the comment thread, act on the answers, then republish.

## Dashboard without `live.py` (database mode)

When the owner asks for a dashboard and the run does not use `live.py`, publish a copy of
`dashboard/tracker.html` whose `<title>` reads "<project> Foreman" (an artifact is named after the `<title>` it was
published with; never publish the bare "Foreman" title) as an Artifact with
`capabilities: {db: {}, user: {scopes: ["profile"]}}`, then seed it from the run sheet with one `ArtifactData`
batch. `dashboard/SCHEMA.md` is the data contract and has every write; `dashboard/seed-example.json` is a working
seed. Record the URL in the run sheet (`dashboard.url`). Do not hand-build a new page per project.

Keep it true, or it is worse than none:
- **Every stage transition** → update the stage's `status` (and `note`) and `meta/state`.
- **Every iteration** → one `log` entry with `ref` (stage or milestone id), `kind`
  (`build` | `review` | `fix`), `round`, `verdict` for reviews, `actor`, and a `link` to the PR
  comment or report. Fix-brief rulings go in as `kind: "decision"` on the same `ref`.
- **Anything added after planning** (a stage or milestone inserted mid-run) → `origin: "added"`,
  `addedAt`, `addedReason`, `order` between its neighbours. Never renumber planned items.
- Read the doc before an update and pass its version (`if_version`); batch related writes.

## Install

From a checkout of the foreman repo (the script is not part of the install), `python install.py` copies the skill to `~/.claude/skills/foreman/`. It loads at the next session start.
