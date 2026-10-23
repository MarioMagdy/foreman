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

(filled after the runs)
