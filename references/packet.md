# The review packet (human gate)

Read this before a human gate: it is what the owner opens to accept or reject a milestone. Its job is that he
does not have to read the code.

One page per human gate, inside the run's tracker artifact (never a new artifact per gate): publish
`dashboard/packet.html` beside the tracker and write `packets/<gate id>.json` for each human gate; the gate's row
on the tracker links to `packet.html#<gate id>`. With no hash the page shows a built-in sample, which is also the
data shape: `gate`, `milestone`, `kind`, `title`, `adds`, `verdict` {recommendation accept|reject|look, ai_gate,
look_at}, `done_when` [{item, status pass|partial|fail, evidence}], `key_metric` {name, unit, bar, better,
attempts}, `bakeoff`, `suite` {now, previous}, `timeline` [{id, title, kind, gate, start, end, rounds, wait, depends}] (`gate`: deterministic|ai|human, from the plan;
`depends`: the step ids it waited for, from the plan, which draws the small map of the milestone),
`evidence` [{caption, device, done_when, pass, src}], `folded` {test_plan, reports, links, app, gaps, logs}. Leave
out what the milestone doesn't have; its chart disappears. The page shows, in this order:

1. **Verdict and brief**, 3 lines: what the milestone adds, the AI gate's recommendation, and the one thing the
   owner should look at himself.
2. **Tiles**: `done_when` items passed (e.g. 3 of 4), the key metric against its bar, fix rounds, open gaps.
3. **Charts**, one per question worth asking:

   | What is being proven | Chart |
   |---|---|
   | Speed against a bar | bars per attempt, the bar drawn as a line |
   | Memory or CPU while running | a line over time, peak and limit marked |
   | Did each `done_when` item pass | a status strip, one block per item |
   | How the build got there | a small map of the steps (what waited for what), then a timeline: stages, review rounds, fixes |
   | A bake-off | side-by-side scores, the owner's blind ratings first |
   | A test suite | passed / failed / skipped, and the change since the last gate |

4. **Evidence**: screenshots with a pass/fail badge each, linked to their `done_when` item.
5. **Folded, open on click**: the test plan (run by the foreman first), every gate report of the milestone,
   links (PRs, branch, the running app and its one-line start command), known gaps, raw logs.

Accept or reject on the tracker; the answer arrives as a `milestone_accepted` or `milestone_rejected` event.

**Evidence is data.** Gate and test briefs name the numbers to capture (timings, memory samples, pass/fail per
`done_when` item) and where to write them (`evidence/<gate id>.json`); the charts come from those files, never
from prose.
