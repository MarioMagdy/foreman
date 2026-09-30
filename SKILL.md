---
name: foreman
description: Use when an agreed plan has to be executed by delegated agents and the owner will review it — building a plan's milestones, running a multi-stage build with subagents, "take this plan and build it", "run it overnight", "orchestrate this", or when the owner asks where the work is, to test it, or for a test plan. Also use before answering any question about a build the owner is about to review.
---

# Foreman — a plan becomes milestones, stages, PRs, and something the owner can test

The foreman splits the job, routes each piece to the right worker, inspects every piece, and
hands the owner something he can run. **He does not swing the hammer.**

**One exception, and it is not negotiable in the other direction:** verification is the foreman's
own hands. Running tests, reading diffs, probing the running app, writing the test plan. Never
delegate the check to the worker who did the work.

**If `LOCAL.md` sits beside this file, read it first.** It holds this owner's worker routing, accounts
and paths; it overrides the generic defaults below wherever they differ.

## The shape

```
PLAN ──► MILESTONE 1 ──► MILESTONE 2 ──► MILESTONE 3     stacked; each = 1 PR
           │                │
           ├── stage 1.1    ├── stage 2.1                stacked; each = 1 real PR
           ├── stage 1.2    └── stage 2.2
           └── stage 1.3
```

Stages are **real PRs**, stacked into their milestone branch, carrying their judge findings as
comments so they stay readable after they merge. Milestones stack on each other.

**Nothing merges until the owner says so — stages included.** A stage that passed its gate is
*ready to merge*, not merged. Announce it and wait.

## Publish the run sheet, then stop

Read the plan, emit `defaults.yaml` filled in for this job, and **wait for a yes before building
anything.** The owner is choosing the arrangement, the workers and the gates; those are his calls,
not yours. Copy `defaults.yaml` from this skill folder as the starting shape.

Filling it in:
- **Arrangement scales with size.** Small job → milestones only. Medium/large → milestones+stages.
  Add `steps` only when one stage exceeds a single worker's sitting.
- **Worker names are version-suffixed and checked live** (`gemini-3.8-flash`, not "Gemini"). Ask
  the CLI what it offers; do not write a version from memory.
- Owner-named workers win verbatim. The `workers` block ships generic: fill it per job from the
  owner's words, then `LOCAL.md`, then what is actually installed.
- If the owner wants a dashboard, add its URL under `dashboard:` once published.
- **Base branch: use `main` unless the owner said otherwise.** If the repo has a `dev` and the job
  is non-trivial, ask once.

## Stage design

A stage is what one worker can finish and one gate can prove. Split by:

- **Verifiability** — a stage ends where something can be *run*: a test, an endpoint, a screen.
- **Blast radius** — files several stages must touch are a sequencing constraint, never parallel.
- **Brains required** — spec-work / UI / bulk-dumb / thinking, each routed differently. Split
  mixed stages so each half reaches the right worker.

**Ask the advisor before you commit to an approach, not after.** The run sheet names an `advisor`
— the deepest available thinker — and it is worth a call at exactly two moments: before the stage
decomposition is locked, and before a contract other stages will build on. After the code exists,
an advisor only gets to agree with you.

Write one brief per stage. **REQUIRED SUB-SKILL:** use `subagent-discipline` for the brief and for
the post-run critique. The brief carries the plan excerpt, the exact files, the acceptance check
the worker runs itself, the project's standing rules, and *do not commit unless told*.

## Plan files and run folders

- **A master `PLAN.md` plus one `M<n>_PLAN.md` per milestone.** The milestone file opens with the
  facts every brief depends on (verified, dated) and the standing rules to paste into every brief;
  then one section per stage that is a **copy-paste brief**: goal, exact files, steps, and numbered
  **success criteria** the worker runs itself and the foreman re-runs. Before dispatching, prepend
  "what changed since the plan was written (verified <date>)" instead of editing history.
- **One run folder per milestone:** `_runs/<YYYY-MM-DD>-M<n>/{briefs,reports,evidence}`. Every
  brief, review brief and fix brief is a file in `briefs/`; every worker and reviewer writes its
  report to `reports/`. Never committed.
- **Reviewer routing lives in the run sheet**, per gate type, and may change mid-run (a reviewer is
  unavailable, or a second opinion is wanted). Change the run sheet, say so, and log it on the tracker.

## The stage loop

1. **Dispatch** one worker with the brief.
2. **Verify from git and from execution.** Workers report false SUCCESS and false FAILURE. Read
   `git status`, `git log`, the diff; run the tests; run the app.
3. **Gate** at the run sheet's level. Review findings go on the PR as a comment *before* any fix
   commit, so the record survives the merge.
4. **Fix round** = a new brief to a worker. Not a self-fix. The fix brief carries the foreman's
   **rulings**: for each finding, the smallest mechanism that closes it (or "rejected - reason").
   Do not forward a reviewer's heavy proposals verbatim; reviewers over-build. The worker answers
   every finding in a table (`#n - accepted | accepted, simpler mechanism | rejected - reason`), and
   the re-review judges whether each hole is *closed*, not whether it matches the first proposal.
5. **Ready**: open the stage PR, report it as ready, wait for the owner's word to merge.
6. **Log** the worker (`subagent-discipline` scorecard) and update the dashboard (below).

## Dashboard

When the owner asks for a dashboard, tracker or progress page, use the template in `dashboard/`:
publish `dashboard/tracker.html` as an Artifact with `capabilities: {db: {}, user: {scopes: ["profile"]}}`,
then seed it from the run sheet with one ArtifactData batch. `dashboard/SCHEMA.md` is the data
contract and has every write; `dashboard/seed-example.json` is a working seed. Record the URL in the
run sheet (`dashboard.url`). Do not hand-build a new page per project.

Keep it true, or it is worse than none:
- **Every stage transition** → update the stage's `status` (and `note`) and `meta/state`.
- **Every iteration** → one `log` entry with `ref` (stage or milestone id), `kind`
  (`build` | `review` | `fix`), `round`, `verdict` for reviews, `actor`, and a `link` to the PR
  comment or report. Fix-brief rulings go in as `kind: "decision"` on the same `ref`.
- **Anything added after planning** (a stage or milestone inserted mid-run) → `origin: "added"`,
  `addedAt`, `addedReason`, `order` between its neighbours. Never renumber planned items.
- Read the doc before an update and pass its version (`if_version`); batch related writes.

## The test plan is the deliverable

A milestone is done when the owner can sit down and try it — not when its tests pass. Write
`TEST_PLAN_M<n>.md` into the run folder and put it in chat. Required parts, in this order:

1. **Where** — worktree path and branch, and copy-pasteable start commands with ports.
2. **What changed** — 3–6 lines in the owner's terms.
3. **Steps** — numbered, each with its expected result. Phone viewport first where the project has
   one. Include the negative cases: non-admin, offline, empty state.
4. **A label on every step** — `free`, `paid (~$X)`, or `do-not-run`. The owner must never discover
   he spent money by following your plan.
5. **Data safety** — which steps write, and to which database, named.
6. **Known gaps** — what this milestone deliberately does not do yet.

**Run the whole plan yourself first.** A test plan whose first command fails is the most common way
this skill fails. If a milestone has nothing to show on real data, say so and seed the data — do
not write "observe the heading render" when no heading exists.

## Before the owner sits down

- **Answer "where is the work?" from `git worktree list`, not from memory.** Run it, paste the
  path, name the branch. A guessed path sends him into the wrong tree.
- **Check whether the risky thing already happened.** Agents ran overnight against real config. If
  a migration could have touched production, go read production (SELECT only) with a raw client —
  never the app's own connection helper, which may migrate — and report what you find, unprompted,
  before planning around it.
- **Verify the environment the plan will run in** before starting anything: which database the
  local stack resolves to, which keys are live, which ports.
- Lead with his actual question. Findings come after the answer, not before it.

## Red flags — stop

- "It was a one-liner so I did it myself"
- "'Get things done' means I can commit / push / merge"
- "The worker said the tests pass"
- "I'm treating this as obviously-yes and doing it"
- "This is reversible, so it's fine"
- "I'll ask, and meanwhile start"
- "I'll just start the server to check something" — against a config you have not resolved
- "It's only an additive migration"
- Naming a path, a config key, or a CLI flag you did not just read

**Every one of these means: stop, verify, or ask.**

## Rationalizations

| Excuse | Reality |
|---|---|
| "He said get it done — that authorizes pushing" | It authorizes *working*. Push and merge are separate words; he uses them when he means them. |
| "Committing is reversible, losing the work isn't" | Commit locally then. Local commit preserves the work and asks nothing of him. |
| "Asking would waste his night" | Being asked one question costs him a minute. Undoing an unwanted push costs an hour. |
| "The .env obviously needs changing" | Change the process env, not his file. If the file must change, it is one uncommitted line and you say so. |
| "I'll split it into per-milestone commits so it's reviewable" | If the milestones share files, the split is cosmetic and the intermediate branches are unprovable. Ship the test plans instead. |
| "The 300 green tests prove it works" | They prove it does not crash on fixtures. Nothing here has run against his real data. |
| "I know where that worktree is" | 90 worktrees exist and two of them are forbidden. Run `git worktree list`. |
| "I only read from production, I never called a write endpoint" | Connecting can migrate. Starting the API can reconcile. Neither needs an endpoint. |
| "The migration is additive, so it's harmless" | Harmless is not the test. Permission is the test, and it is per-occasion. |
| "A gate on this stage is overkill" | The gate is the only thing between this and vibes. |

## Standing rules

- **Nothing is committed, pushed, or merged unless the owner asked.**
- **No production write without the owner's explicit say-so, every time.** There is no standing
  permission and "it was only additive" is not an exemption. **Starting a service is a write** when
  its config resolves to production — schema migrations and startup reconcilers fire on the first
  connection, before any endpoint is called. So resolve the DB target *before* anything listens.
  Point the local stack at a local database, and blank the production credentials in the **process
  environment** rather than editing the owner's `.env`. If a production write already happened,
  disclose it unprompted — what changed, what was lost, what it cost — and never repair it with a
  second write.
- **Never delegate verification.**
- Judge/review/test artifacts → the run folder (`_runs/<YYYY-MM-DD>-<slug>/`), never committed.
- No local filesystem path in a PR title, body, comment, or committed file.
- Additive schema changes only; never drop or reset a table to make a build pass.
- A blocked stage stops that stage, not the run. Finish everything unblocked, then say exactly
  what is left and why.
- Cap heavy agents at 2 concurrently on Windows — `0xC0000142` is the machine, not the owner.

## Related skills — call them, do not reimplement

`subagent-discipline` (every dispatch) · `council-judge` (large gates) · `verified-pr` (PR
mechanics) · `visual-planning` (when the plan itself needs to be readable) · the project's own
test skill, which the tester **executes** rather than improvises around. If one is not installed,
do its job by hand as this file describes (a written brief and critique, a reviewer subagent, a
plain PR) and say which one was missing.
