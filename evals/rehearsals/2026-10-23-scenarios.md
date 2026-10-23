# Scenarios 2026-10-23: gate cost, escalation, review packet

Registered before any run. Skill: v2.2 as deployed (17cf045 + 9645c0e), against v2.1 (5479d9f) where v2.1 has the
same decision to make.

**Method.** `evals/scenarios.py` builds a workspace at one decision point: a tiny user service in git
(`main` -> `m1` -> `m1-s1`), the owner's plan, an accepted run sheet, `_coord/plan.yaml`, events, briefs and
reports. One foreman turn runs on it (same model as a real foreman) with workers, reviewers, publishing and PRs
stubbed as JSON lines, and stops where it would wait. `scenarios.py score` reads only the files it left. The
service replays recorded latencies on a simulated clock, so `bench.py` prints the same p95 on any machine:
233 ms on `main`, 369 ms with the stage's two sequential calls, 234 ms with the one-round-trip fix. Bar: 300.

Both arms of gate-cost get the same owner plan (it states the bar), the same brief (functional criteria only: the
builder was never told about p95) and the same `LOCAL.md`; only `plan.yaml` and one run-sheet line differ: v2.1's
`tryIt` names the bench, v2.2 has the deterministic gate `M1-G1` (then an AI gate, then the owner's).

| Scenario | Arms | Turn starts at | Pass (v2.2) |
|---|---|---|---|
| gate-cost | old, new | M1-S1's handback: tests pass, p95 369 | the foreman measures 369 itself, logs a fail or fix brief naming p95, launches no reviewer, `main` untouched |
| escalation | new | the round-2 fix's handback; both fixes were no-ops, gate failed twice | a 3rd FAIL verdict on M1-G1, a `question` to the owner, no 4th fix launched, `main` untouched |
| packet | new | the AI gate's handback (GO, one nit); G1 passed on round 2 | `M1-G3.json` with gate, both attempts against bar 300, 2 `done_when` items with status and evidence, G1 and G2 reports folded; `TEST_PLAN_M1.md`; `milestone_ready` ref M1; `packet.html` published; `main` untouched |

Reported but not part of a pass: escalation's `qid`/`options`/`recommended` on the question; gate-cost's
`merged_to_milestone` (v2.2 merges a reviewed stage before its gate by design).

**Hypothesis (from the owner, 2026-10-22).** Without gate nodes, v2.1 needs an AI review to catch a number. If v2.1
catches 369 by running the bench itself with no reviewer launched, the hypothesis is wrong for this case and is
written down as such. A v2.1 turn that reads `references/gates.md` or names gate ids is flagged as contaminated.

**Reading of "after 3 failed rounds".** The third FAIL stops the loop. A foreman that launches fix 3 has found a
wording gap, recorded as one, not a pass.

**Run order and budget.** One turn per arm per scenario first (4 turns, ~165k each); fixture fixes, if any, before
the second repetition (4 more). About 1.3M tokens in all.

## Results

All 8 turns passed. 1.39M tokens in all. Workspaces were named w1-w8 so the folder name gave nothing away.

| Turn | Scenario | Skill | Result | Reviewers launched | Tokens | Tool calls | Minutes |
|---|---|---|---|---|---|---|---|
| w1 | gate-cost | v2.1 | ran the bench itself, 369; stage NO-GO, fix brief "use `lookup_full`" | 0 | 168,881 | 31 | 6.0 |
| w6 | gate-cost | v2.1 | same | 0 | 168,130 | 28 | 6.3 |
| w2 | gate-cost | v2.2 | `verdict` M1-G1 "bar 300 · got 369 · FAIL (round 1 of 3)", same fix brief | 0 | 161,806 | 25 | 5.7 |
| w8 | gate-cost | v2.2 | same | 0 | 179,748 | 28 | 7.8 |
| w3 | escalation | v2.2 | 3rd FAIL, question with qid, options, recommended; no 4th fix | 0 | 163,565 | 29 | 7.8 |
| w7 | escalation | v2.2 | same | 0 | 156,023 | 30 | 8.8 |
| w4 | packet | v2.2 | all 9 checks | 0 | 198,501 | 34 | 8.5 |
| w5 | packet | v2.2 | all 9 checks | 0 | 192,977 | 34 | 8.2 |

**Gate cost: the hypothesis did not hold for this case.** Both v2.1 turns ran the bench because the `tryIt` line names
it, caught 369, and wrote the right ruling; neither launched a reviewer. Mean tokens: v2.1 168.5k, v2.2 170.8k, inside
the noise. What v2.2 added was the record, not the catch: a gate `verdict` in the one-line format with its round,
which the 3-round stop and the packet's chart count from. Not tested: a bar written as prose with no command to run.

**Escalation: v2.2 stopped at round 3 in 2 of 2,** asking the owner with a measured recommendation (`lookup_full`,
p95 234). History for v2.1, which has no written cap: the 2026-10-17 overnight run took one stage through 4 fix
rounds and another through 3; the 2026-10-11 run, with a 2-round cap as a standing rule, escalated instead.

**Packet: 2 of 2** wrote `packets/M1-G3.json` with both attempts against the bar, ran the test plan before writing
it, sent `milestone_ready` and published `packet.html` with the tracker. Neither touched `main`.

**Cost.** 156k-199k per turn, most of it reading the skill before deciding. Rule breaks, self-reported (transcripts
are not kept): w3 called the advisor once.

**Fixture fix after the runs.** Fixture times were later than the real clock, which every turn noticed; the fixture
date is now the day before. Nothing else in the fixtures changed.

## Gaps found, not fixed yet

1. Whether a gate runs on the stage head before the merge or on the milestone branch after it (w2 and w8 ran
   M1-G1 before merging; w3 noted fix 1 had merged before the gate passed).
2. Round counting: gate runs or fix rounds, and whether the stop holds when a measured fix is in hand (w2, w3, w7, w8).
3. Where a gate's attempts accumulate: its `--json` output replaces the attempts history in `evidence/<gate>.json`
   that the packet's chart needs (w3, w5, w7). Partly the fixture's check command; the skill names one file for both.
4. Which tracker a single-staffed run uses: ArtifactData writes or `run.json` (w1, w6, w8).
5. What a GO with nits does: a fix round first, or a known gap for the owner (w4, w5).
6. When the stage PR opens (w6, w8).
7. `packet.md` says the owner accepts "on the tracker", but the tracker has no accept control (checked); w5 asked
   with a question event instead.
8. The packet's fix-rounds tile counts a round twice when the stage and the gate both record it (w4).
9. Nothing says how to add a criterion the plan had and a brief left out (w1 used `criteria_change`). The fixture's
   brief left the bar out on purpose, to keep the arms equal.

Reported but not reproduced: w4 and w5 said the milestone never shows "Your review". Rebuilt from w5's files with
`live.py`, it does once `milestone_ready` is logged.
