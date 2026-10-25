# Tracker data contract

`tracker.html` is a template: it has no project data in it. Everything it shows comes from the artifact's
runtime database (`db` capability), which the foreman writes with the **ArtifactData** tool and viewers may add to
from the page. This file is the contract between the two.

Rules that apply everywhere:

- Every field not marked **required** is optional. The page renders documents that carry only the required fields,
  so a tracker seeded before a field existed keeps working when the template is republished.
- Timestamps are ISO-8601 UTC strings (`2026-09-30T09:40:00Z`). Never epoch numbers.
- Ids are one path segment: letters, digits and `_ - . ~ : @ +`.
- People are stored as opaque user ids (`authorId`, `addedBy`), never names. The page resolves names when it
  renders. The foreman writes `actor` (a plain string such as a model name) instead.
- `origin: "added"` marks anything created **after the plan was approved**: a stage or milestone inserted
  mid-run, or a note. The page gives it a distinct colour and an `added` label. Seeded plan items carry
  `origin: "planned"` or no `origin` at all.

## Collections

### `meta/state` (one document) - the header

| Field | Type | Req | Meaning |
|---|---|---|---|
| `project` | string | | Name shown in the masthead, under "Foreman", and in the browser tab as "<project> Foreman". Default "Build tracker". |
| `subtitle` | string | | One line under the name. |
| `focus` | string | | "Now:" what is happening right now. |
| `waitingOn` | string | | "Waiting on:" who owes what (usually the owner's decisions). |
| `updated` | ISO string | | When the foreman last updated the header. |

### `milestones/<id>` - one per milestone (doc id = milestone id, e.g. `M1`)

| Field | Type | Req | Meaning |
|---|---|---|---|
| `title` | string | yes | Milestone name. |
| `order` | number | yes | Sort key. Fractions are fine (`1.5` sits between 1 and 2). |
| `tryIt` | string | | "You can try:" what the owner can do when it is done. |
| `status` | status | | Only used when the milestone has no stages; otherwise the status is derived from its stages (all merged = merged, any blocked = blocked, all ready/merged = ready, any started = running). |
| `origin` | `"planned"` \| `"added"` | | See above. |
| `addedAt` | ISO string | | When it was added (with `origin:"added"`). |
| `addedReason` | string | | Why it was added. Shown in the detail panel. |
| `addedBy` | user id | | Set by the page when a viewer adds it. |

### `stages/<sid>` - one per stage (doc id = `sid`, e.g. `1.2`)

| Field | Type | Req | Meaning |
|---|---|---|---|
| `sid` | string | yes | Stage id; same as the doc id. |
| `milestone` | string | yes | The milestone's id. |
| `order` | number | yes | Sort key inside the milestone. Insert between two stages with the midpoint of their orders. |
| `title` | string | yes | Stage name. |
| `status` | status | yes | `planned` `briefed` `running` `verifying` `review` `fixing` `ready` `merged` `blocked`. |
| `worker` | string | | Who builds it (version-suffixed model name, or `foreman`). |
| `depends` | string[] | | Stage ids this stage needs. Drawn as arrows inside the milestone lane. |
| `note` | string | | One-line state note under the title. |
| `pr` | URL | | The stage PR. |
| `origin`, `addedAt`, `addedReason`, `addedBy` | | | As for milestones. |

`ready` means the gate passed and the PR is ready to merge. It never means merged.

### `log/<id>` - activity, iterations and notes (doc id: any unique id, e.g. `e042` or a timestamp)

| Field | Type | Req | Meaning |
|---|---|---|---|
| `at` | ISO string | yes | When it happened. (`ts` is read as a fallback; write `at`.) |
| `text` | string | yes | What happened, one or two sentences. |
| `ref` | string | | A stage `sid` or milestone id. Entries with `ref` also appear in that item's detail panel; entries without `ref` appear only in the overall log. |
| `kind` | `build` \| `review` \| `fix` \| `note` \| `decision` | | `build`, `review` and `fix` are **iterations** and are listed under "Iterations" in the detail panel; the others are listed under its log. |
| `round` | number | | Iteration round (`1`, `2`, ...). Shown as `r1`, `r2`. |
| `verdict` | string | | Gate result for a review: `GO`, `GO WITH CHANGES`, `NO-GO` (coloured green / amber / red). |
| `actor` | string | | Who did it: a model name, `foreman`, `owner`. |
| `link` | URL | | PR comment, report, or commit. |
| `origin` | `"added"` | | Set by the page on notes viewers add. |
| `authorId` | user id | | Set by the page on notes viewers add. |

The database holds at most 25,000 documents. One log document per event is fine for any single project; if a
tracker ever approaches the cap, prune old unreferenced log entries.

## Foreman writes (ArtifactData)

Every call takes the tracker's `url`. A write to a document that already exists needs `if_version` (the version
you last read); creating a new document does not. A batch is at most 50 writes and is applied all-or-nothing.

**Seed a plan** (after the owner approves the run sheet): one batch of `set` writes for `meta/state`, every
milestone, every stage (`origin:"planned"`) and a first log entry. `seed-example.json` in this folder is a
complete, working example of this batch (its `writes` array is the `writes` argument):

```json
{ "action": "batch", "url": "<tracker url>", "writes": [
  { "op": "set", "collection": "meta", "doc_id": "state", "data": { "project": "Invoice export", "focus": "Plan approved; stage 1.1 briefed.", "waitingOn": "nothing", "updated": "2026-09-28T09:00:00Z" } },
  { "op": "set", "collection": "milestones", "doc_id": "M1", "data": { "order": 1, "title": "Export contract and API", "tryIt": "call GET /invoices/export?month=2026-09", "origin": "planned" } },
  { "op": "set", "collection": "stages", "doc_id": "1.1", "data": { "sid": "1.1", "milestone": "M1", "order": 1, "status": "briefed", "title": "Export contract", "worker": "sonnet-5.5", "depends": [], "origin": "planned" } },
  { "op": "set", "collection": "log", "doc_id": "e001", "data": { "at": "2026-09-28T09:00:00Z", "text": "Run sheet approved." } }
] }
```

**Move a stage's status** (read the stage first to get its version):

```json
{ "action": "batch", "url": "<tracker url>", "writes": [
  { "op": "update", "collection": "stages", "doc_id": "1.1", "if_version": 3, "data": { "status": "review", "note": "Contract committed; deep review running." } },
  { "op": "set", "collection": "log", "doc_id": "e005", "data": { "at": "2026-09-28T12:00:00Z", "text": "Contract ready for review.", "ref": "1.1", "kind": "note", "actor": "foreman" } }
] }
```

**Record an iteration** (one log entry per build, review or fix round, always with `ref`):

```json
{ "action": "set", "url": "<tracker url>", "collection": "log", "doc_id": "e006",
  "data": { "at": "2026-09-28T12:30:00Z", "ref": "1.1", "kind": "review", "round": 1, "verdict": "NO-GO",
            "actor": "gpt-6-sol", "text": "9 findings; see the PR comment.", "link": "https://github.com/org/repo/pull/12#issuecomment-1" } }
```

A fix round is the same with `"kind": "fix", "round": 2`; the re-review is `"kind": "review", "round": 2`.
Record the foreman's rulings for a fix brief as `"kind": "decision"` on the same `ref`.

**Add a stage in between** (after planning; `order` = midpoint of the neighbours' orders):

```json
{ "action": "batch", "url": "<tracker url>", "writes": [
  { "op": "set", "collection": "stages", "doc_id": "1.2a", "data": { "sid": "1.2a", "milestone": "M1", "order": 2.5, "status": "planned",
    "title": "Stream large exports", "worker": "sonnet-5.5", "depends": ["1.2"],
    "origin": "added", "addedAt": "2026-09-29T16:10:00Z", "addedReason": "Found in the 1.2 gate: memory blow-up on large months." } },
  { "op": "set", "collection": "log", "doc_id": "e009", "data": { "at": "2026-09-29T16:10:00Z", "ref": "1.2a", "kind": "note", "origin": "added",
    "actor": "foreman", "text": "Added stage 1.2a after the 1.2 gate." } }
] }
```

A milestone in between is the same shape in `milestones` (doc id e.g. `M1a`, `order` between its neighbours).

**Update the header** (read `meta/state` first):

```json
{ "action": "update", "url": "<tracker url>", "collection": "meta", "doc_id": "state", "if_version": 7,
  "data": { "focus": "Stage 1.2 in review.", "waitingOn": "Owner: merge PR #12.", "updated": "2026-09-29T10:00:00Z" } }
```

## Viewer writes (from the page)

A viewer who may write (Contributor or above) sees "+ add stage here" between stages, "+ add milestone"
between milestones and "Add note" in a detail panel. Each opens a small form, then a review step that states
exactly what will be written; nothing is written until **Save**. The page writes the same shapes as above with
`origin:"added"`, `addedAt`, `addedReason`, and the viewer's id (`addedBy` / `authorId`), plus a log entry with
`ref` recording the addition. A viewer who cannot write does not see the controls; if a write is refused anyway,
the page says so and hides them.

## Publish recipe

1. Copy `tracker.html` to the scratchpad, change its `<title>Foreman</title>` to `<title><project> Foreman</title>`
   (the artifact takes its name from that title, so every tracker is not called "Foreman"), and publish the copy
   with the Artifact tool, declaring exactly:

   ```json
   "capabilities": { "db": {}, "user": { "scopes": ["profile"] } }
   ```

   `db` gives the page the shared database with default rules (everyone admitted reads; Contributor and above
   write). `user` gives it the viewer's id for `addedBy` / `authorId`, `can("data.write")` to show or hide the add
   controls, and names (`profile` scope) to show who added a note.
2. Seed it with one ArtifactData `batch` built from the run sheet (see "Seed a plan").
3. Read back once: ArtifactData `list` on `stages` and `log` and check the counts.
4. Put the tracker URL in the run sheet (`dashboard.url`).

**Upgrading an existing tracker** to this template: publish to the same `url`, and pass the full `capabilities`
above. Omitting `capabilities` on a republish keeps the old declaration, so a tracker first published with only
`{db:{}}` would never get `user`. Existing data renders unchanged; new fields are optional.

## Run mode: `run.json` beside the page

When a file `run.json` sits next to the page (same folder locally, or published with the Artifact as
`files: {"run.json": ...}`), the page renders it instead of the database, read-only, and re-reads it
every 10 s. It has the same `meta`, `milestones`, `stages` and `log` shapes as above, plus a `run`
object for track mode: `attention`, `staffing`, `jobs`, `pool`, `handoffs` (per stage) and `files`.
`track-mode/live.py build` writes it from a run's `_coord/` folder. It is plain JSON and may be edited
by hand; nothing in the HTML changes per project.

**Questions.** Each open question is one `attention` entry per `qid`: `from` (who raised it), `to` (who
holds it now), `text` (the question as first asked), `chain` (every hop: `{from, to, at, text}`), and,
when given, `options` and `recommended`. A question passed on (a manager asks, the orchestrator cannot
decide and asks the owner) is a second `question` event with the same `qid`. Questions held by
`owner` show their options as buttons plus a free-text box. **Send answers to Claude** posts all picks as
one comment and sends it to the Claude session watching the artifact. If no session is watching, it
posts a plain comment, which the next check-in reads. If sending isn't possible from this view
(opened locally, or the viewer is not an editor), it copies the text to paste into the chat. Publish
with `capabilities: {comments: {}}` so the send works.

## Testing without the runtime

Opened outside claude.ai (or with no database), the page shows a "no database" state with a **Show sample data**
button. `tracker.html?demo` or `tracker.html#demo` opens straight into the sample. The sample is the same batch as
`seed-example.json`; adding stages, milestones and notes works on it in the tab and saves nothing. For automated
tests, a script that runs before the page (for example Playwright's `addInitScript`) may set
`window.__TRACKER_FIXTURE__ = { milestones: [{id, ...}], stages: [...], log: [...], meta: {...} }` to render any
data shape.
