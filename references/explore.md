# Explore milestones

Read this when the work is uncertain: the owner wants to try options, iterate on what he finds, run a bake-off,
or apply a batch of his test feedback.

A planned milestone is a fixed slice stacked on the one before it. An explore milestone is open-ended and sits to
the side:

- `kind: explore` in `plan.yaml`. Its branch, `explore/<slug>`, comes off the base branch, not off the stack.
- Its stages (build and spike) may `need` each other. A build stage merges into the explore branch after its stage
  review and whatever AI or deterministic gates the run sheet names; no human gate per stage.
- **Nothing in a planned milestone `needs` a stage of an explore milestone.** When the stack needs something from
  it, the owner promotes that piece: it becomes a stage of a planned milestone.
- Spikes and bake-off losers never merge. A bake-off is several prototypes of one idea, rated blind; the owner
  rates first and his scores stay sealed.
- It grows as the owner tests: new stages carry `origin: added`. When the base branch moves, merging the base
  into the explore branch is a stage of its own, so the final merge is not a fight.
- It reaches the base only on the owner's explicit word, after its human gate. He can ask for its review packet
  at any time, not only at the end.
- Its `done_when` says what the owner will have decided or seen by the end ("I picked a vault from measured
  results"), not a feature list.

## Feedback batches (was "polish sprint", owner 2026-10-19)

When the owner's test feedback arrives, do not bolt the fixes onto the feature milestones: open an explore
milestone for them, finish it, then go on with the plan.

- Step 0 merges what the owner kept into one base branch; every fix branches off that base, in parallel, with no
  `needs` between fixes, and merges back.
- Small explicit fixes suit the cheapest capable builder (e.g. a Gemini Flash); each brief names its files and a
  CSS file of its own, so parallel stages don't collide.
- Gates per fix: targeted tests, typecheck and build. The full suite runs once on the merged result, then the
  owner tests.
- It ends with a short test list of the fixed items and the next plan.
