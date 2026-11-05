# Briefs: writing a worker's brief and grading what comes back

Read this when you write a brief for any worker and `subagent-discipline` is not installed. A worker has only the
brief: it cannot ask you what you meant, so anything left out is guessed.

## What every brief carries

1. **Role and scope.** One sentence each: what the worker is (builder, fixer, reviewer, auditor) and the one stage it owns.
2. **Facts it cannot discover**, each marked `verified <date>` or `not verified`. Versions, ports, which database a
   config resolves to, what an earlier stage changed. A fact that is not marked is read as a guess.
3. **Files it owns and files it must not touch.** Parallel workers get disjoint owned lists; if two stages need the
   same file, run them one after the other.
4. **Numbered steps, each with its check.** Step 3 is not done until its check passes. End the list with: "If anything
   deviates from this brief, stop and report the raw state (commands and their output). Do not improvise."
5. **The exact commands that must pass**, copied from CI or the run sheet, and the path where the evidence goes
   (a file in `reports/` or `evidence/`, not the chat).
6. **The invariant and the failure it must survive**, not the mechanism. "A retry after a half-written file must not
   duplicate rows" lets the worker find a good fix; "add a lock" does not.
7. **The report format**, with a section "What I could not test" that may not be empty or skipped. End with the
   STATUS block from `SKILL.md`.
8. **The run's brief lines** from `references/delegation.md` (mailbox line, progress line, time cap, testing rule,
   handback).

## Scope and safety lines (paste into every brief)

- No edits outside the owned files. If the fix needs one, stop and say which.
- Stage only the files you own, by name. Never `git add -A` or `git add .`: it picks up other workers' files and scratch output.
- Commit to your stage branch after each numbered step. Never push.
- Never kill processes by name (`taskkill /im`, `pkill`): you will kill another worker's. Stop only process ids you started.
- Never `git stash`: the stash is shared by every worktree of the repo. Set work aside with a commit.
- Use your own scratch folder (`_scratch/`), not a shared temp path.
- Never write a model's name into a commit message or file; say "the model that did the work".

## Earlier work

- If a worker or an earlier attempt left partial work, say so in the brief and add: "Treat it as untrusted. For each
  part, keep, repair or rewrite it, and say which and why." Without this a worker builds on a bug it did not write.

## Grading what comes back

- Grade against the brief **as written**, not against what you wish you had asked. A missing instruction is the
  brief's fault; log it as that.
- Check the report's claims by running them (`references/workers.md`); a worker's "done" is a claim, not a result.
- Record one line per worker: model, job, what it got right, what you had to fix, and seven grades from 0 to 5, in
  this order: rule following, task understanding, recovering from unknowns, output quality, honesty, autonomy,
  verification rigor. Each grade has its evidence; a grade with no evidence is not recorded. The same seven go into
  the machine's run log (`scores/runs.py add`, SKILL.md stage loop step 6).
- A 5 means nothing to fix in that dimension, not "fine". Most workers have something; grade it. Re-verify before
  any 5: rerun the commands, read the diff.
- A model that did well on a small brief has not shown it can do a large one. Note the job's size beside the score.
- When agents rate other agents, hide who made each piece of work; ratings given with names attached follow the name.
