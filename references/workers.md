# Workers: checking a handback and driving worker CLIs headlessly

Read this when a worker hands back, and before you start a worker from a command line, if no driver skill for that
CLI is installed. The CLI facts here are ones seen to hold; check `--help` when in doubt.

## Handback honesty checks (do all of them, from files, not from the report)

- Every path the report cites as evidence exists, and the report file itself exists.
- **Count what the job should have written** (files, rows, tests) and compare with the report's number. "Processed all
  items" with half the output files is a failure.
- Judge a live check by its **success field** (the status, `ok`, the exit of the real call), not by how many rows came back.
- **Exit 0 or `STATUS: DONE` is not delivered.** Delivered = the commits are on the branch and the check you ran passes.
- **Fallback, cached or synthetic output is a demo.** If the worker fell back to fake data or an old file, the report
  must say so; if it does not, treat the report as false.
- Every number in a report names where it came from (command, file, line). A number with no source is not used.
- Read `git status`, `git log` and the diff. Files outside the owned list mean the worker went out of scope.

## Always pass the model

On every subagent or CLI call, pass the model explicitly. Left out, the worker inherits the session's model, which is
often the most expensive one and not the one you routed.

## Headless traps (any CLI)

- **Decide permissions before launch.** A headless run that hits an unanswered permission ask hangs, or exits 0 with no
  work done. After any run that did nothing, read stderr first.
- **A brief over about 8 KB goes in a file**; the prompt says "read <absolute path> and follow it". Long prompts on a
  command line are truncated or mangled.
- **A time cap on the outer command kills the status block.** Make the handback files (`HANDOFF.md`, reports), not
  the final message, the thing you read.
- **The model chooses its own command timeouts.** Name every long command in the brief with the timeout to use.
- **"Read-only" in a brief makes some models claim they are in plan mode** and do nothing. Write "write only <path>"
  instead, and name the one file the reviewer may write.
- **Usage limits hang silently.** Before re-queuing a stalled job, read the CLI's own log and send a one-line probe
  prompt; a probe that hangs is a limit, not a bug in your brief.
- Blank secrets the worker does not need in its process environment (`references/delegation.md`).

## opencode

- Close stdin (`< /dev/null`, or `< NUL` on Windows); an open stdin makes `opencode run` wait.
- Headless, it rejects every permission ask. It refuses to read `*.env` files and paths outside the working
  folder: give it copies inside the worktree, or settle the permission block in the folder's `opencode.json` first.
- If `opencode models` lists only free models, the account is not logged in; fix auth before routing paid work to it.
- Several standalone runs at once lock its database; use one shared server (`track-mode/LAUNCHER.md`).

## codex

- Pipe the prompt on stdin: `codex exec - < brief.md`. A prompt in the arguments can be eaten by option parsing.
- Unattended runs need `-c mcp_servers={}` so a slow MCP server does not stall startup.
- Builders: `-s workspace-write -c approval_policy="never"`; reviewers: `-s read-only` (`references/delegation.md`, section 5).

## Claude subagents

- Subagents take the aliases `sonnet`, `opus`, `haiku`; write the alias and say so in the run sheet.
- A subagent notifies you when it finishes; do not poll it in a loop.
