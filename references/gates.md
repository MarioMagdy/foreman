# Plan nodes and gates

Read this when writing `_coord/plan.yaml` (architect pass) and whenever a gate runs.

## The plan.yaml shape

```yaml
milestones:
  - id: M1
    kind: planned            # planned (stacked, the default) | explore (references/explore.md)
    title: One key, on your say-so      # what the owner gets, in his words; no layer names, no "[gate N]"
    adds: A Claude session can use one key for one command, and only after you approve it.   # 1-2 sentences
    done_when:               # 2-4 items, each something the owner sees or does, not what a builder did
      - I approve a request in my own terminal and the command works; the key value appears nowhere in the transcript.
      - I deny the next request and the session is refused.
stages:
  - { id: M1-S1, milestone: M1, kind: spike, title: Which vault meets the bar, needs: [], builder: <model> }
  - { id: M1-S2, milestone: M1, kind: build, title: The runner, needs: [M1-S1], builder: <model> }
  - { id: M1-G1, milestone: M1, kind: gate, gate: deterministic, title: No key value leaks,
      check: "pytest tests/leak -q; scan the session transcript for the canary values",
      bar: "0 canary hits in 5 leak attempts", needs: [M1-S2] }
  - { id: M1-G2, milestone: M1, kind: gate, gate: ai, title: Milestone review,
      check: "<reviewer> reviews the whole milestone diff against done_when", needs: [M1-G1] }
  - { id: M1-G3, milestone: M1, kind: gate, gate: human, title: Your review, check: review packet, needs: [M1-G2] }
```

`kind` defaults to `build`. Gate ids are `M<n>-G<k>`. Old runs carry a one-line `tryIt` instead of `adds` and
`done_when`; the tracker still shows it. `python <the skill's folder>/evals/plan_check.py <plan.yaml>` checks this shape.

## Node kinds

| kind | Produces | Merges | Done when |
|---|---|---|---|
| **build** | code on a stage branch | into its milestone branch, after its stage review | its stage gate passes (`settings.stage_gate`, the stage reviewer) |
| **spike** | a decision with evidence: measurements, a short report, a throwaway prototype | never | the gate after it accepts the decision |
| **gate** | a report | nothing | per its type, below |

The per-stage review stays inside its build stage; it is not a node. A gate node checks across stages, or against
a bar.

**When the plan leaves a choice open** (it lists options, or says evaluate, compare, try or pick), that choice is a
spike followed by a gate: deterministic when the plan states a measurable bar, human when it is the owner's taste
or trade-off. Later stages that depend on the choice `need` that gate. A recommended answer in the owner's
questions is not a substitute: it builds on a choice nobody tested.

Where the spike sits: one with a measurable bar may sit inside a planned milestone. One the owner picks from (taste,
a bake-off) goes in an explore milestone, because a planned milestone's only human gate is the one that closes it
(`plan_check` counts them); the winner is then promoted into a planned milestone, or built in the explore one.

## Gate types

| type | Passes | Report |
|---|---|---|
| **deterministic** | on its own, when the measurement meets `bar` | one line from the template below |
| **ai** | on its own, when the reviewer says go | full: what was checked, findings, verdict |
| **human** | only when the owner accepts it on the tracker | the review packet (`references/packet.md`), holding every earlier report of the milestone |

**Defaults.** Every planned milestone ends with an AI gate, then a human gate, and every other node of the
milestone leads into the human gate. Add a deterministic gate wherever a `done_when` item or the plan has a number
or a pass/fail command (speed, memory, a leak scan, a suite written before the build). Add an AI gate in the middle
of a long milestone where two features inside it meet. The owner may switch any default off in the run sheet.

**Deterministic report**, one line per criterion, with the measurement kept as data (`evidence/<gate>.json`):

```
p95 response < 500 ms · bar 500 · got 250 · previous 710 · PASS   (cmd: python bench.py --runs 20; raw: evidence/M1-G1.json)
```

A check that has never failed proves nothing: the `previous` column shows that it can.

**When an auto gate fails**, its report goes into a fix brief for the stages it names, and the gate runs again.
After 3 failed rounds it stops and becomes a `question` event for the owner, with the reports attached.

## Tests written before the build (opt-in, per gate)

When a criterion is sharp enough to test (an API contract, a limit, a parser's behaviour), the gate's owner (the
foreman, or the track manager) commits the tests before the builder starts and records their hashes in the brief.
The builder does not change those files; the gate fails if a hash changed. A builder that thinks a test is wrong
logs a `test_dispute` event (`ref` = the test, `summary` = why) and continues on the rest; the test's author rules
on it: fix the test, or send the build back.
