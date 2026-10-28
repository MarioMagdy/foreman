---
name: foreman
description: Use when an agreed plan has to be executed by delegated agents and the owner will review it — building a plan's milestones, running a multi-stage build with subagents, "take this plan and build it", "run it overnight", "orchestrate this", "foreman init" or "initialize" (with or without "and start"), or when the owner asks where the work is, to test it, or for a test plan. Also use before answering any question about a build the owner is about to review, and when the owner asks for a dashboard, tracker or progress page for a build.
---

# Foreman — a plan becomes milestones, stages, PRs, and something the owner can test

The foreman splits the job, routes each piece to the right worker, inspects every piece, and
hands the owner something they can run. **It does not swing the hammer.**

**One exception, and it is not negotiable in the other direction:** verification is the foreman's
own hands. Running tests, reading diffs, probing the running app, writing the test plan. Never
delegate the check to the worker who did the work. (In track mode a track manager verifies its
stages; it never builds, so the rule holds. The orchestrator still runs every milestone test plan.)

**If `LOCAL.md` sits beside this file, read it first.** It holds this owner's worker routing, accounts,
paths and house rules (`LOCAL.md.example` shows the shape); it overrides the generic defaults below wherever they
differ. Without it, ask the owner and fill the run sheet per job.

**Read your harness file next.** The rules in this file hold on every harness. Seven steps depend on it: starting a
worker or manager, waking when a job hands back, scheduled check-ins, showing the owner the run, taking the
owner's answers, resuming a manager and updating the owner, and naming models. In Claude Code read `harness/claude-code.md`; anywhere else read
`harness/generic.md`. Where this file says to do one of those seven, do it the way your harness file says.

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

**Stages merge into their milestone; the owner merges milestones** (the default). Push every
stage branch and open its PR into the milestone branch. When a stage passes its gate (verified by the foreman,
review findings on the PR, fixes done), the foreman merges it into the milestone branch without asking. The
milestone PR (into the previous milestone's branch, or the base for the first) is what the owner reviews.

**Every milestone ends at the owner's gate** (`human_review: per-milestone`, the default). Once its test plan
runs clean, the milestone waits for the owner, who tries the whole feature and then accepts it or asks for
changes. Only the owner merges a milestone PR, after accepting it. In `plan.yaml` the gates are nodes: every planned
milestone ends with an AI gate, then this human gate, so the owner sees what waits on them (`references/gates.md`). A branch that holds several milestones is a
place to try them together, never a way to merge them past their gates (a morning summary once offered exactly that).

**Milestones are working slices** (the default): one feature or one fix per milestone, which the owner tests as a
whole. Its title says what it adds in the owner's words; it carries `adds` (1-2 sentences) and `done_when` (2-4 things
they see or do). Each milestone is something the owner can use end to end (its
data, backend and screen together), so its test plan is a real use, not a list of API calls. Do not cut
milestones by layer (service / engine / screens): layer milestones tangle (one cannot ship without a fix in
another) and need an integration branch before anything can be tested.

### Planned and explore milestones

A **planned** milestone is the fixed slice above, stacked on the one before. An **explore** milestone holds
uncertain work: trying options, iterating on what the owner finds, bake-offs, and their batches of test feedback.
It branches off the base, grows as they test, nothing in the stack depends on it, and
it reaches the base only on their word. Read `references/explore.md` before planning one.

## `foreman init`: write the plan and the run sheet, then stop

`foreman init` (or "initialize") does the setup and nothing else: read the plan, do the architect pass (next
section), write the run sheet (`run-sheet.md`: the questions as prose, then `defaults.yaml` filled in for this job in a
YAML code block, with the workers you propose),
`_coord/plan.yaml`, `PLAN.md` + `M<n>_PLAN.md`, and the setup questions in one batch (`_coord/questions.md`), all in the
run folder (below); show them (on the tracker if they
asked for one, else in chat), and **wait for a yes before building anything.** Any other first ask to build a plan
("take this plan and build it") is `init` too: the owner's review is the default. They are choosing the arrangement, the workers and the gates; those are their calls,
not yours. When they change something ("opencode for M2's builds"), edit the run sheet and plan files, say what changed,
and wait again. Log their yes as a `decision` event (actor `owner`, ref `run-sheet`); a restarted foreman that finds no
such event waits. Copy `defaults.yaml` from this skill folder as the
starting shape. Its `architecture`, `staffing`, `profile`, `events`, `restart` and `plan_files` blocks are
**required**: a run sheet with any of them blank, or whose plan files are not written yet, is not ready to show.

**The defaults are the answer unless the owner overrides them; confirm them before work starts.** At setup, put
every default that shapes the run to the owner as a numbered question whose recommended answer is the skill default
(milestones as working slices,
stage merges (foreman, into the milestone, after the gate), milestone merges (owner only), human review (per
milestone), base branch, stage gate, reviewers, live traffic and caps). No building until the owner has accepted
them; "use the defaults" is a full answer, and it is not a mandatory interview. What the owner changes goes into
the run sheet; everything else stays the default. An instruction such as "no merges tonight" is read against these
defaults (it stops milestone merges); if it could also mean stage merges, ask.

**`init and start`** (the owner's words: "init and start", "initialize and go", "init, no review"): write and show the same
files, then start without waiting. Every setup question takes its recommended answer, marked `assumed` in
`questions.md` and listed in `standing_orders`; they can overturn any of them later, for stages not yet started. Log a
`decision` event (actor `owner`, ref `run-sheet`, summary "init and start"). It skips only the wait for the run
sheet: milestone gates, milestone merges, the base branch, live traffic and money beyond the run sheet's caps still
wait for their word, and a question only they can answer (a key, an account) blocks only the stages that need it. If their
words could mean either, ask.

Filling it in:
- **Arrangement scales with size.** Small job → milestones only (one build stage per milestone, plus its gates).
  Medium/large → milestones+stages.
  Add `steps` only when one stage exceeds a single worker's sitting.
- **Worker names are version-suffixed and checked live** (`gemini-3.8-flash`, not "Gemini"). Ask
  the CLI what it offers; do not write a version from memory. Where the harness only offers aliases (Claude Code
  subagents take `sonnet`, `opus`, `haiku`), write the alias and say so.
- Owner-named workers win verbatim. The `workers` block ships generic: fill it per job from the
  owner's words, then `LOCAL.md`, then what is actually installed.
- **`settings`** (stage gate, review and human-review levels, verification depth, expected minutes, hard stop,
  mailbox interval, usage stop lines) are the owner's to change: show them, then copy the block into
  `_coord/plan.yaml` so the dashboard header shows it (always including `human_review`). `references/delegation.md` applies them to every worker;
  paste the ones that bind a worker (stage gate, hard stop) into each brief.
- If the owner wants a dashboard, add its URL under `dashboard:` once published.
- **Base branch: the repo's default branch (`main`, `master`, ...) unless the owner said otherwise.** If the repo
  has a `dev` and the job is non-trivial, ask once.
- **PRs need a GitHub remote.** Check `git remote -v` and `gh auth status`; with neither, propose
  `stage_prs: local` (branches and merges only, review findings in `reports/`) as the recommended answer.
- **Keep the run folder out of git:** add `_runs/` to the repo's `.git/info/exclude` (the owner's `.gitignore` is theirs).

## Architect pass (before the run sheet)

Think like the architect of the run, not its first worker. Its outputs fill the run sheet's
required blocks:

1. **`architecture`** — draw the stage dependency graph. Write down: the **critical path** (the
   longest chain of `needs`), the **tracks** (chains that can progress without waiting on each
   other), the **joins** (stages that need two tracks; each is its own stage with its own tests and a named owner;
   in track mode the owner is a manager, because the orchestrator manages managers, never stages), and the **width** (most stages that could run at once).
2. **Effective parallelism** = the smallest of: width, worker slots (the launcher's pool, see track
   mode), the heavy-agent cap, quotas, the live-manager cap. Order the riskiest and the contract
   stages first, and keep parallel tracks out of the same files.
3. **`staffing`** — `single` (this session runs everything) or `tracks` (one manager per track, see
   track mode), with the reason.
4. **`profile`** — models, fallback chains and caps, copied from `profiles/default.yaml` and
   adjusted. Fallbacks listed here are **pre-approved**: once the owner says yes, a dead or
   rate-limited model is replaced along its chain without asking again. Without an approved chain
   a dead model stalls its stage until the owner answers.
5. **`events`** and **`restart`** — where every hand-off is logged, and how each actor is rebuilt
   from files if its session dies.
6. **Facts before findings.** Write the deployment shape (workers, replicas, proxies) into `environment`, and read
   it before believing any audit's severity. Pin the toolchain once (`.python-version`, one prepared venv per
   integration worktree) and check it before the first build.
7. **Storage or comparison?** For any identity / normalization stage, ask whether the goal needs stored data to
   change or only the comparison. Prefer the comparison: a stored-form change spread side effects through three
   review rounds and was rebuilt.
8. **Accounts and quotas before the first job** (at start, not at init). Check that every paid worker account has
   funds (one tiny call each) and count jobs per quota-limited worker: route fix rounds to the fallback, keep the quota for new
   stages. A paid account can run dry mid-run (HTTP 402), and a quota-limited worker can run out partway through.
9. **Questions up front, in one batch.** Every decision a stage could block on (access and keys,
   authority, budget, which fallbacks may run, who decides what while the owner is away). Anything
   unanswered gets a default and a named decider in `standing_orders`.
10. **`plan.yaml`, in the shape `references/gates.md` gives (read it now).** Milestones with `adds` and
   `done_when`; build, spike and gate nodes; each planned milestone closed by an AI gate, then the human gate. An
   open choice in the plan (options listed, "evaluate", "try") becomes a spike and a gate, not a question with a
   recommended answer. Check the file with `python <this skill's folder>/evals/plan_check.py _coord/plan.yaml`.

## Stage design

**Stage ids are `M<n>-S<k>`** ("M1 stage 1"): the milestone number, then the stage's number inside it, in build order. Never letters (`M1a`). A split stage is `M1-S3.1`; a head-to-head build is `M2-S2` with the builds named in the summary, never a new id. Verdicts, branches, briefs and PR titles all use this id, and reports show it with the stage title ("M1-S1 Runner").

A stage is what one worker can finish and one gate can prove. Split by:

- **Verifiability** — a stage ends where something can be *run*: a test, an endpoint, a screen.
- **Blast radius** — files several stages must touch are a sequencing constraint, never parallel.
- **Brains required** — spec-work / UI / bulk-dumb / thinking, each routed differently. Split
  mixed stages so each half reaches the right worker. Route by shape too (`workers.route_by_shape`): read-only
  audits, rulings-based fixes and continuations, greenfield features and money/security stages each have a
  natural worker. Backend and front end are separate jobs.
- **Merge-friendly** — each stage writes its own changelog section and its own contract section (or a marked
  block), so the final merge needs no hand edits (in one run four of five merges conflicted in the same two files).

**Ask the advisor before you commit to an approach, not after.** The run sheet names an `advisor`
— the deepest available thinker — and it is worth a call at exactly two moments: before the stage
decomposition is locked, and before a contract other stages will build on. After the code exists,
an advisor only gets to agree with you.

Write one brief per stage. Read `references/delegation.md` for everything around the worker (its prepared
worktree, skills and permissions per role, progress file and mailbox, testing rule from `settings.stage_gate`,
soft and hard stop, handback files; scripts in `delegation/`). `subagent-discipline`, when installed, covers the
brief and the post-run critique. Without the scripts (another OS), do it by hand: one worktree per stage branch (`git worktree add`, dependencies
installed, one quick test run before the brief goes out); the worker appends a line to `_scratch/PROGRESS.md`
after each step, reads `_scratch/MAILBOX.md` after each step (a soft stop is a line there), and writes
`_scratch/HANDOFF.md` when it stops early. `track-mode/LAUNCHER.md` relies on the same three files. The brief carries the plan excerpt, the exact files, the acceptance check
the worker runs itself, the project's standing rules, the brief lines from `references/delegation.md` (or the three file rules above), and *commit to your stage
branch after each numbered step; never push*. Reviewer briefs say *put your report in your final reply*. Every
brief ends by requiring the worker's **status block** as the last thing it writes:

```text
STATUS: DONE      criteria: <n>/<N> self-checked · evidence: <paths>
STATUS: UNSURE    question: <one line> · tried: <one line>
STATUS: TOO_HARD  why: <one line>
STATUS: BLOCKED   waiting on: <stage or input>
```

## Plan files and run folders

- **A master `PLAN.md` plus one `M<n>_PLAN.md` per milestone.** The milestone file opens with the
  facts every brief depends on (verified, dated) and the standing rules to paste into every brief;
  then one section per stage that is a **copy-paste brief**: goal, exact files, steps, and numbered
  **success criteria** the worker runs itself and the foreman re-runs. Before dispatching, prepend
  "what changed since the plan was written (verified <date>)" instead of editing history. They live in the run
  folder, never next to the owner's plan: Windows file names ignore case, so a `PLAN.md` written
  beside the owner's `plan.md` replaces it.
- **One run folder per run:** `_runs/<YYYY-MM-DD>-<slug>/` in the target repo (`<run>` elsewhere in this file). It
  holds `run-sheet.md`, `PLAN.md`, the `M<n>_PLAN.md` files, `_coord/`, and per milestone
  `M<n>/{briefs,reports,evidence}`. Every brief, review brief and fix brief is a file in `briefs/`; every worker and
  reviewer writes its report to `reports/`. Never committed. Commands in this file that name `_coord/...` run from
  the run folder.
- **Reviewer routing lives in the run sheet**, per gate type, and may change mid-run (a reviewer is
  unavailable, or a second opinion is wanted). Change the run sheet, say so, and log it on the tracker.

## The stage loop

1. **Dispatch** one worker with the brief, once every stage it needs has passed its gate, into a prepared worktree
   (`delegation/prepare_worktree.py`, or by hand as above; never a cold one). While it runs, look at
   `_scratch/PROGRESS.md`, talk through `_scratch/MAILBOX.md`, and stop softly there first
   (`launcher.py soft <job>` for launcher jobs); overrunning `expected_minutes` is a flag, not a kill. If a
   needed stage is built but not yet gated, and the interface used from it is frozen (contract or
   committed signature), the stage may start **provisional**: mark it so on the tracker and in its
   `brief` event, never call it ready before the stage it needs, and rebase it if that stage changes.
2. **Verify from git and from execution.** Workers report false SUCCESS and false FAILURE. Read
   `git status`, `git log`, the diff; run the tests; run the app.
3. **Gate** at the run sheet's level. Review findings go on the PR as a comment *before* any fix
   commit, so the record survives the merge.
4. **Fix round** = a new brief to a worker. Not a self-fix. The fix brief carries the foreman's
   **rulings**: for each finding, the smallest mechanism that closes it (or "rejected - reason").
   Do not forward a reviewer's heavy proposals verbatim; reviewers over-build. The worker answers
   every finding in a table (`#n - accepted | accepted, simpler mechanism | rejected - reason`), and
   the re-review judges whether each hole is *closed*, not whether it matches the first proposal.
   **A ruling on a normalizer or identity rule is not READY until a diff on real data against the base branch
   says what it costs** (rows lost, joins gained). A ruling accepted as "intended" can quietly lose real data.
5. **Merge**: the stage PR (body carries the ticket link in whatever format the project's CI checks)
   merges into the milestone branch once its gate passes; the next stage builds on the merged milestone branch.
   When the milestone's last stage is in, run the milestone review and the test plan on the milestone branch,
   then open (or update) the milestone PR and send `milestone_ready` to the owner.
6. **Log** the worker (`subagent-discipline` scorecard, or a few lines in `reports/`), append the hand-off events (below), and
   update the dashboard (below).

**Events.** Every hand-off is one JSON line in the actor's own file
`_runs/<run>/_coord/events/<actor>.jsonl` (one writer per file; the foreman writes the owner's answers into
`owner.jsonl`; readers merge by `ts`):
`{"ts","actor","to","kind","ref","summary","artifact"}` with `kind` one of `brief`, `handback`,
`status`, `clarification`, `criteria_change`, `review`, `verdict`, `fix_brief`, `verify`,
`fallback`, `hang`, `quota`, `question`, `answer`, `decision`, `staff_request`, `staff_approved`,
`join`, `milestone_ready`, `milestone_accepted`, `milestone_rejected`, `test_dispute`. A gate's result is a `verdict`
event with `ref` = the gate id. Full texts live in `briefs/` and `reports/`;
the event points at them. `milestone_ready` (to the owner, ref `M<n>`, once its test plan runs clean) puts the
milestone on "Your review"; the owner's `milestone_accepted` (actor `owner`) unlocks its merges;
`milestone_rejected` sends it back to its stages.
This is the trail the owner's live view is drawn from, so it starts at the first brief.

## Track mode (two levels of managers)

Switch it on in the architect pass when **both** hold: there are 2 or more tracks that can run in
parallel, and the run will outlast one working session (about a day, or more than ~12 stages).
Otherwise `staffing: single` and everything above applies unchanged. How managers start, wake and check in is in
your harness file.

| Role | Does | Never does |
|---|---|---|
| Orchestrator (this session) | Architect pass; owns `orchestration.md` global parts, `staffing.yaml` approvals, contracts, standing orders; starts every manager; runs each milestone's test plan; the **only** one who talks to the owner | build; micro-manage a track |
| Track manager (profile `manager` model) | Runs one track per its **charter** (`track-mode/CHARTER.md`, filled per manager): dispatches stages through the launcher as soon as their inputs are gated (or provisional, per the charter), verifies each stage, runs the gate, clarifies and tightens criteria, requests sub-managers, escalates | build; talk to the owner; loosen a criterion; start a manager |

- **Coordination folder** `_runs/<run>/_coord/` — one writer per file:
  `orchestration.md` (orchestrator; each manager edits only its own track's section),
  `staffing.yaml` (managers add `requested` rows; only the orchestrator sets `approved`/`active`/
  `retired` and starts managers; cap 4 live, 3 levels deep), `profile.yaml`, `standing-orders.md`,
  `contracts/` (orchestrator), `tracks/<id>.md` (that manager's status, in-flight jobs, evidence),
  `shared/<actor>.md` (facts other tracks need, append-only), `questions.md`, `events/`.
- **Worker launcher** (Windows with opencode workers; elsewhere workers start as your harness file says and you
  write their events) — where it runs, every opencode builder, reviewer and tester goes through it, never directly. See
  `track-mode/LAUNCHER.md`: one `opencode serve` shared by the run, a pool of slots, and the
  `brief`/`handback`/`hang`/`quota` events written for you. The orchestrator runs
  `launcher.py --coord _runs/<run>/_coord start` before the first brief and `stop` at the end; each
  check-in runs `health` and restarts the pool when it says `DOWN`.
- **Live view** — the build tracker (`dashboard/tracker.html`) drawn from the run's files by
  `track-mode/live.py` (needs PyYAML). The architect pass writes `_coord/plan.yaml` (milestones with
  `adds` and `done_when`; stages with `milestone`, `kind`, `title`, `needs`, `builder`, `track`, and gate fields; see
  `references/gates.md`); the rest comes from the
  events, the launcher, `staffing.yaml`, `tracks/` and `questions.md`. At a glance: now / waiting
  on, a needs-attention box (open questions, stuck stages, staff requests; hidden when empty), the
  team line, milestones, the dependency map (from 5 milestones up: a milestone map on top, and tapping a milestone
  shows the map of its stages), and per stage its manager, worker, live job time and
  provisional tag; a Map / Timeline switch (timeline: one bar per stage, grouped by manager,
  coloured by phase, with stuck and question marks); and "Managers and their agents": the
  orchestrator on top with what waits on it, then each manager with its stages, the agents working
  for it now and its open asks. On click: iterations, log and every hand-off of a stage; the staffing tree,
  slots and track files. The page never changes: all data is one `run.json` beside it, which a locally served page re-reads every
  10 s and anyone may edit (a published copy changes only when you republish it). `live.py build --coord <dir>` writes it; `live.py serve --coord <dir>`
  serves the page locally; showing it to the owner is a harness step.
  **The owner answers questions where they see the run.** Every `question` event carries `qid`, and when it is for
  the owner, `options` and `recommended`. A question you pass on keeps the manager's `qid`, so the view shows who
  raised it and each hop it took. Log one `answer` event per `qid` (actor `owner`), act on the answers, then refresh
  the view. Events may carry `state`, `verdict`, `provisional_on` or `qid` to make
  stage states exact; fix rounds go through the launcher with `--fix`.
- **Two channels.** Updates and facts go to files (`tracks/<id>.md`, `shared/`, events); the
  orchestrator reads them at every check-in. A manager **ends its turn only for a question that
  blocks**: it appends it to `questions.md`, returns with its id, and is resumed with the answer.
- **Wake on handback, in any staffing.** Pick up a finished job the moment it hands back (`handback|hang|quota|failed`
  in `events/launcher.jsonl`), the way your harness file says. In one run a 30-minute check-in alone left jobs
  sitting finished for about 3 hours.
- **Restart.** The orchestrator schedules a check-in every 30–60 min when the run
  starts and removes it at the end, where the harness can schedule; elsewhere the check-in is the start of each of
  your own steps (harness file). It is the safety net behind waking on handback. Each check-in reads `staffing.yaml` and the track files,
  restarts any dead or silent manager from its track file with a resume brief, and sends the owner
  the update, at most hourly (unless the profile says otherwise), the way the harness file says. A fresh orchestrator rebuilds the run from
  `_coord/`.

`launcher.py` is Windows-only (ctypes, taskkill) and drives opencode workers only; elsewhere, run workers through your harness's own
subagents or CLIs and write the same events by hand.

## Dashboard

When the owner asks for a dashboard, tracker or progress page, use `dashboard/` (`tracker.html` and `packet.html`)
fed by `track-mode/live.py`, shown the way your harness file says. Never hand-build a new page per project. Keep it
true, or it is worse than none: refresh it at every stage transition and every build, review and fix round, and
mark anything added after planning as added (never renumber planned items).

## The test plan is the deliverable

A milestone is done when the owner can sit down and try it — not when its tests pass. Write
`TEST_PLAN_M<n>.md` into the run folder and put it in chat; at the human gate it sits inside the review packet
(`references/packet.md`, read it before the gate). Required parts, in this order:

1. **Where** — worktree path and branch, and copy-pasteable start commands with ports.
2. **What changed** — 3–6 lines in the owner's terms.
3. **Steps** — numbered, each with its expected result: first the milestone's `done_when` items, one or more
   steps each, then the rest. Phone viewport first where the project has
   one. Include the negative cases: non-admin, offline, empty state.
4. **A label on every step** — `free`, `paid (~$X)`, or `do-not-run`. The owner must never discover
   they spent money by following your plan.
5. **Data safety** — which steps write, and to which database, named.
6. **Known gaps** — what this milestone deliberately does not do yet.

**Run the whole plan yourself first.** A test plan whose first command fails is the most common way
this skill fails. If a milestone has nothing to show on real data, say so and seed the data — do
not write "observe the heading render" when no heading exists.

**Two gates every multi-stage run needs before "ready", because stage gates miss what crosses stages:**
- **Milestone review on the top of the stack** by the strongest reviewer the run sheet names. It finds
  what green stage gates and CI let through, because each stage gate sees only its own diff.
- **End-to-end on real saved data across every repo the run touched**, no live traffic: the real chain
  (export → next tool → import → the client file), plus the app started on a throw-away copy and clicked.
  Write it as `TEST_PLAN_E2E.md`. On the same run it found 8 seams no single-repo plan could see (a hint
  printing the old unguarded command, contacts lost to invisible characters, a match file nothing read).

## Before the owner sits down

- **Answer "where is the work?" from `git worktree list`, not from memory.** Run it, paste the
  path, name the branch. A guessed path sends them into the wrong tree.
- **Check whether the risky thing already happened.** Agents ran overnight against real config. If
  a migration could have touched production, go read production (SELECT only) with a raw client —
  never the app's own connection helper, which may migrate — and report what you find, unprompted,
  before planning around it.
- **Verify the environment the plan will run in** before starting anything: which database the
  local stack resolves to, which keys are live, which ports.
- Lead with their actual question. Findings come after the answer, not before it.

## Red flags — stop

- "It was a one-liner so I did it myself"
- "'Get things done' means I can merge a milestone or push to the base branch"
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
| "They said get it done (or init and start) — that authorizes merging the milestone" | It authorizes *working*: stage branches, stage PRs, stage merges into the milestone. Milestone merges and anything on the base branch are the owner's words, used when meant. |
| "Committing is reversible, losing the work isn't" | Commit locally then. Local commit preserves the work and asks nothing of them. |
| "Asking would waste their night" | Being asked one question costs them a minute. Undoing an unwanted push costs an hour. |
| "The .env obviously needs changing" | Change the process env, not their file. If the file must change, it is one uncommitted line and you say so. |
| "I'll split it into per-milestone commits so it's reviewable" | If the milestones share files, the split is cosmetic and the intermediate branches are unprovable. Ship the test plans instead. |
| "The 300 green tests prove it works" | They prove it does not crash on fixtures. Nothing here has run against their real data. |
| "I know where that worktree is" | Dozens of worktrees can exist, and some are off limits. Run `git worktree list`. |
| "I only read from production, I never called a write endpoint" | Connecting can migrate. Starting the API can reconcile. Neither needs an endpoint. |
| "The migration is additive, so it's harmless" | Harmless is not the test. Permission is the test, and it is per-occasion. |
| "A gate on this stage is overkill" | The gate is the only thing between this and vibes. |

## Standing rules

- **Nothing reaches the base branch (dev / main) or a milestone merge unless the owner asked.** Standing
  permissions: a worker commits to its own stage branch after each step, locally; the foreman
  pushes stage and milestone branches, opens their PRs, and merges a gated stage into its milestone branch.
- **No production write without the owner's explicit say-so, every time.** There is no standing
  permission and "it was only additive" is not an exemption. **Starting a service is a write** when
  its config resolves to production — schema migrations and startup reconcilers fire on the first
  connection, before any endpoint is called. So resolve the DB target *before* anything listens.
  Point the local stack at a local database, and blank the production credentials in the **process
  environment** rather than editing the owner's `.env`. If a production write already happened,
  disclose it unprompted — what changed, what was lost, what it cost — and never repair it with a
  second write.
- **Never delegate verification.**
- Judge/review/test artifacts → the run folder (`_runs/<run>/M<n>/`), never committed.
- No local filesystem path in a PR title, body, comment, or committed file.
- Additive schema changes only; never drop or reset a table to make a build pass.
- A blocked stage stops that stage, not the run. Finish everything unblocked, then say exactly
  what is left and why.
- **Bulk git cleanup snapshots its target list once, before acting, and never runs while builds start**: a lazy
  per-repo listing removes build worktrees created while it runs.
- **Long verification runs in the foreground in chunks under 10 minutes**, or as a launcher job. Background test
  runs and wrapper processes were reaped under memory pressure while the session idled; watch worker PIDs, not
  wrappers. Agent-tool subagents notify on their own and survived every reap.
- **A stage gate runs what CI runs.** Name the exact command CI uses (e.g. `pytest tests/`, not three subfolders),
  and, where the repo has CI, treat a green CI run on the pushed head as part of READY (with `stage_prs: local`,
  the gate's own run of that command is the evidence). Builders that run only the folders they touched miss
  failures elsewhere.
- **Never cancel a running `DROP DATABASE`**: it can leave the database invalid. If it hangs on a checkpoint, use a new
  database name instead.
- **Standing rules a brief pastes in must not name a model**: a commit-trailer line naming the previous builder
  made the next one sign as the wrong model. Say "the model that did the work".
- Cap heavy agents at 2 concurrently on Windows: above that, process creation fails with `0xC0000142`.
  Opencode jobs go through the launcher's single `opencode serve` (an attached run is one process),
  never as parallel standalone `opencode run`s — those lock its database.

## After the run: post-mortem

Every run ends with `postmortems/<yyyy-mm-dd>-<slug>.md` (where: `LOCAL.md`, else beside the run folders): numbers (stages GO, jobs, fix rounds, first-pass review rate, time per stage, interventions, model usage where the harness reports it, e.g. Claude Code via `track-mode/usage_split.py`), what went well, what went wrong with root cause and a proposed skill change, and how each agent behaved. Open problems from earlier post-mortems are read before the next run sheet.

## Related skills — call them, do not reimplement

`subagent-discipline` (every dispatch) ·
`council-judge` (large gates) · `verified-pr` (PR
mechanics) · the project's own
test skill, which the tester **executes** rather than improvises around. If one is not installed,
do its job by hand as this file describes (a written brief and critique, a reviewer subagent, a
plain PR) and say which one was missing.
