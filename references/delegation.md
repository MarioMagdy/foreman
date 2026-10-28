# Delegation: the runtime contract for every worker

Everything between "the brief is written" and "the work is back": the workspace, the channels, the stop, the
handback. The scripts are in `<foreman>/delegation/` (stdlib Python, each has `selftest`): `prepare_worktree.py`,
`mailbox.py`, `hook.py`. Below, `<D>` means that folder. `prepare_worktree.py` is Windows-first (junctions, a `.cmd`
shim for agy); on macOS or Linux make the worktree by hand and keep the `_scratch/` files and the brief lines below.

## 1. Before launch

1. **Prepare the workspace with the script, never inside the worker's clock** (a cold venv can cost a worker 5-18
   minutes):
   ```
   python <D>/prepare_worktree.py --repo <repo> --path <wt> --branch <M1-S2-...> --base <default branch> \
       --harness <claude|opencode|codex|agy> --role <builder|reviewer|auditor> \
       [--python 3.12] [--shared-venv <dir>] [--web <subdir> --node-modules-from <dir>] \
       [--copy <src>=<dst>] --quick-test "<one fast test command>" [--interval <mailbox_interval_min>]
   ```
   It makes the worktree, syncs the venv on the pinned Python (`--shared-venv` when the job does not change
   dependencies), installs or links web deps, copies test data, creates `_scratch/` with `MAILBOX.md` and
   `PROGRESS.md`, writes the harness hook bundle (git-excluded, never committed), runs the quick test, and writes
   `_scratch/PREPARED.json` with the launch line, the timings and the secret-looking env var names. A failing quick
   test stops here: fix the environment, do not start the worker.
2. **Blank the secrets** listed in `blank_these_env_vars` in the worker's process environment (never edit `.env`).
   A worker inherits the environment it is started from, so leave only the keys it needs.
3. **Skills per role:** headless workers cannot answer questions, so skills that stop to ask (brainstorming) and
   orchestration skills (foreman itself, multi-model panels) stay off. A reviewer gets the project's own review skill,
   named in the brief. Write "do not load other skills" in judge briefs. opencode workers run with
   `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` (the launcher sets it) so they do not load every skill folder twice.
4. **Permissions per role:** builders may edit and run commands but never push, hard-reset, clean or delete
   branches; reviewers and auditors cannot edit (they reply with their report). How each harness enforces it is in
   the table in section 5.

## 2. What every brief must contain

Paste these, filled in:
- The mailbox line, verbatim (unannounced, a model treats the mail as a prompt injection and refuses it):
  > Messages from your orchestrator may arrive while you work, headed [MAILBOX from the orchestrator] (appended to a
  > tool result or as a system message). They come from the person who briefed you. Follow them.
- "After each numbered step: commit it, then append one line to `_scratch/PROGRESS.md`:
  `python <D>/mailbox.py note . "<step n done: what>"`." Commit-after-every-step keeps a hard stop cheap.
- For codex until its hook is trusted (section 5): "and read `_scratch/MAILBOX.md`; follow any new line".
- "No single command over <N> minutes; wrap slow ones with `timeout <N*60-20>`." (opencode tells the model to raise
  its timeout when one expires; agy has no per-command limit.)
- The testing rule from the run setting `stage_gate` (section 4).
- Handback: "end by writing `_scratch/HANDOFF.md` (done, left, how to continue, test status) and your STATUS block."
  Reviewers: "put your report in your final reply" (the launcher saves it).
- The expected time (`expected_minutes`) so the worker knows its budget.

## 3. While it runs

- **Look:** `python <D>/mailbox.py progress <wt>` (last progress lines, last tool call, idle minutes, handoff yes/no).
- **Talk:** `python <D>/mailbox.py send <wt> "<text>"`. Delivery is at the worker's next tool call or model call,
  never in the middle of a running command. On agy the idle heartbeat also delivers it while the model waits on a
  background task (every `mailbox_interval_min`, early if mail arrives).
- **Hang:** `python <D>/mailbox.py hang <wt> --minutes <N>` exits 1 when neither `PROGRESS.md` (the model) nor
  `ACTIVITY.log` (the hook, one line per tool call) grew for N minutes. The launcher uses the same files. A single
  long blocking command looks like a hang on purpose: that is the case to look at.
- **Overrun:** at 1.5x `expected_minutes` flag it at the check-in and ask in the post-mortem "should it have taken
  longer?"; it is not a kill. Hard stop only when the progress files stopped growing for `hard_stop` minutes, or at 3x.

## 4. Testing rules (the run setting `stage_gate`)

- `full-suite` (default): the worker runs the whole suite inside the stage and fixes its own failures before handing
  back. Only `full_suite_slots` workers (default 1) run a full suite at once on one machine: the worker takes the lock
  (`_coord/locks/full-suite`, create-exclusive; wait and re-check if it exists, delete it when done). Its time is in
  `expected_minutes`.
- `targeted`: the tests for what it touched plus the project's always-run list (security matrix, contract tests).
- `none`: no tests by the worker (copy changes, docs).
- Whatever the gate, the orchestrator re-runs the stage's targeted tests itself and reads the worker's suite output;
  the full suite runs once more at each milestone integration (first merge, not the last).

## 5. Harness adapters

| | Mail in (installed by `prepare_worktree.py`) | Clock | Soft stop | Hard stop, keeping context | Permissions headless |
|---|---|---|---|---|---|
| **Claude** session (`claude -p`) | `PostToolUse` hook `additionalContext` (`--settings _scratch/claude-settings.json`) | `date` | mailbox | kill, then `claude -p --resume <id>` | `--permission-mode acceptEdits` + deny list in the settings file; reviewers `--allowedTools` |
| **Claude** subagent (Agent tool) | SendMessage | `date` | SendMessage | SendMessage "stop, hand off" | the agent definition |
| **opencode** (launcher) | plugin `.opencode/plugins/delegation-mailbox.js`, `tool.execute.after` | `date` | `launcher.py soft <job>` | `POST /session/<id>/abort` (kills even a blocking command), then `opencode run --attach <url> --session <id> "write HANDOFF.md now"` | workdir `opencode.json` `permission` block per role (written if the repo has none) |
| **agy** | `.agents/hooks.json`: `PreInvocation` system message before every model call; `Stop` heartbeat while idle | `[clock]` note every model call; `schedule` timer | mailbox | kill, then `agy --conversation <id> -p "write HANDOFF.md now"` | without the skip flag agy may only read files: the first `run_command` ends the whole run with no output, so a reviewer that must run `git diff` or tests is launched like a builder; builders need `--dangerously-skip-permissions`, guarded by the hook's deny list. **cwd must be the worktree** or no hook loads |
| **codex** (`codex exec`) | `.codex/hooks.json` `PostToolUse`, runs only once trusted (see below); until then the brief's read-the-mailbox rule | `date` | mailbox | kill, then `codex exec resume <thread_id> "write HANDOFF.md now"` (thread id = first `--json` event) | `-s workspace-write -c approval_policy="never"` builders, `-s read-only` reviewers |

The hook writes the session id to `_scratch/SESSION_ID` (Claude, codex, agy); opencode's is in the launcher's job
record. That is the `<id>` for the resume commands.

Known limits:
- The aborted opencode client exits 0. Abort through the launcher (`cancel`), which records it, or a self-aborted job
  can look like a clean handback.
- `codex queue --thread <id>` did not reach a running `codex exec`. Do not use it as the mailbox.
- codex project hooks run only after you trust them once (per hook entry). Either trust the hook interactively once,
  or rely on the brief's read-the-mailbox rule.
- Whether agy's hook `deny` holds under `--dangerously-skip-permissions` is not proven. Treat the agy builder guard as
  a seatbelt, not a lock: worktree only, secrets blanked. To check it yourself, in a scratch folder prepared for agy
  whose deny list blocks `whoami`, ask agy to run `echo one`, `whoami`, `echo three` as three separate commands; pass =
  `whoami` blocked, the other two ran.
- agy's heartbeat holds the turn up to `mailbox_interval_min`, so a background command that finishes meanwhile is
  noticed up to that late; keep it 1-3 min. Each heartbeat is a model call, capped at `--max-heartbeats` (15).

## 6. Stopping

1. **Soft:** `mailbox.py stop <wt> [--why ...]` (or `launcher.py soft <job>`). The worker finishes its step, commits,
   writes `_scratch/HANDOFF.md`, ends with STATUS.
2. **Grace period:** one step or 5 minutes, whichever is longer. Watch `mailbox.py progress`.
3. **Hard:** the harness's hard stop (table). Every harness above resumes with full context, so ask the resumed
   session for the handoff. If even that fails, the orchestrator writes `HANDOFF.md` from `git log`, `git status`,
   `PROGRESS.md` and `ACTIVITY.log`.

## 7. Handback and after a crash

- Handback = the STATUS block + `_scratch/HANDOFF.md` + commits. Verify from git and from execution, never from the
  report.
- **Crash or kill with no handoff:** read `git log` / `git status` in the worktree, `PROGRESS.md`, `ACTIVITY.log`; for
  agy also its task logs under `~/.gemini/antigravity-cli/brain/<id>/`. Resume the same session (table) with "you were
  stopped; write HANDOFF.md from what you did", or start a fresh worker with a continuation brief that lists what is
  already committed and what is uncommitted.
- Remove the worktree only after its work is merged or saved elsewhere (`git worktree remove`).
