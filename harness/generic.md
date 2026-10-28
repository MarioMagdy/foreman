# Foreman on any harness

Read this when the session is not Claude Code (codex, opencode, a Gemini CLI, anything else that loads `SKILL.md`
folders). `SKILL.md` holds the rules; this file says how to do its harness-dependent steps with plain files and
command-line tools.

## The seven harness steps

| Action | Anywhere |
|---|---|
| Start a worker or manager | A separate run of an agent CLI (`opencode run`, `codex exec`, a Gemini CLI), each in its own prepared worktree with its brief as a file. On Windows with opencode workers, `track-mode/launcher.py` runs the pool and writes the events for you. Managers are separate CLI runs too: this harness has no subagents. |
| Wake on a handback | No outside wake-up exists. Between your own steps, read `_coord/events/launcher.jsonl` (or each worker's exit and its `_scratch/PROGRESS.md` time) and pick up what finished. |
| Scheduled check-ins | None. Tell the owner at the start that the run moves only while a session is open. |
| Show the owner the run | From the run folder, start `python <skill>/track-mode/live.py serve --coord _coord` in the background (it runs until stopped) and give the owner its local URL (default `http://127.0.0.1:8765/`). Review packets open at `/packet.html#<gate id>`. |
| Take the owner's answers | In the chat, or by editing `_coord/questions.md`. Log one `answer` event per `qid` (actor `owner`), as on the page. |
| Resume a manager, update the owner | A manager that ended with `QUESTION <id>` is resumed by re-running it with the answer (codex: `codex exec resume <thread id> "<answer>"`), or started fresh from its track file. Owner updates are a short chat message at the start of your steps, at most hourly. |
| Name models | Ask the CLI what it offers (`opencode models`; for codex, probe an id with a one-line prompt) and write the exact, version-suffixed name. |

## Events you write by hand

Without the launcher, write each hand-off yourself: one JSON line per event in
`_coord/events/<actor>.jsonl` (`brief` when a worker starts, `handback` with its STATUS block when it ends, `hang`
when its progress file stops growing for the run's hang limit). The live view and the post-mortem read only these
files.

## Install

From a checkout of the foreman repo (the script is not part of the install), `python install.py --harness agents` copies the skill to `~/.agents/skills/foreman/`, which codex and opencode read.
For another harness, `python install.py --dest <its skills folder>/foreman`.
