# Review: reviewers, judge panels and PR review

Read this when you run a stage or milestone gate and `council-judge` or `verified-pr` is not installed. A reviewer's
job is to find what the builder and the tests missed, not to confirm the work.

## The reviewer's method

1. **State the change's intent** in two or three lines before looking for faults. Review against that intent, not against taste.
2. **Walk realistic cases through the diff**, reading the code path for each: empty input, a boundary value, a failure
   halfway through, two things at once (concurrency), hostile input, and real volume (the row count the live data has).
   A case the reviewer did not trace is a case it did not review.
3. **Every verdict cites file and line.** A finding with no file and line, or an approval that names none, is
   rejected and the reviewer is rerun.
4. **Style and types are CI's job.** Do not spend a review on formatting, naming or lint; run those as gate commands.

## Who reviews

- **One lens per reviewer.** Three lenses cover most work: intent and logic; scope (did it change only what the brief
  allowed, and everything it should); security and performance. One reviewer told to check everything checks nothing deeply.
- **Reviewers start clean.** Never fork or copy the orchestrator's session into a reviewer, and never show it the
  worker's report: both carry the builder's reasoning, and the reviewer then agrees with it.
- With one model available, run several subagents of that model, each with a different lens. Same model, different brief.
- Review and judging use the strongest model the run sheet has, whatever the builder used.

## What is reviewed

- **A frozen commit.** The brief names the commit hash; the report names it again. A review of a moving branch
  reviews nothing in particular.
- **Large gates get a panel:** two or three reviewers on different lenses (and different models where you have them).
  Read their reports yourself; do not ask one reviewer to summarise the others.

## After the review

- **A re-review goes through every earlier finding** and says for each: closed, open, or made worse. It judges whether
  the hole is closed, not whether the fix matches the first proposal.
- **After a fix, re-review only the fix**: the diff from the reviewed commit to the fix commit, the files it touches
  and every earlier finding, through every lens (fixes break neighbours). A full re-review of the whole milestone
  only when the fix touched files outside the findings or changed an interface. Each full re-review costs as much as
  the first review.
- **The foreman checks the two most consequential claims itself** (run the command, read the lines) before
  accepting a verdict.
- **Disagreement is settled by checking.** Two reviewers disagree: run the case, read the code. Never average
  scores or take the majority.
- **Suspect a fast, unanimous approval, or a high score with no evidence.** Rerun one reviewer with the brief
  "assume this has a defect; find it" and a different lens.
- Post findings on the PR **before** the fix commit, so the record survives the merge (`SKILL.md`, stage loop).
- Say in the owner's update what was reviewed and through which lens; a review lowers risk, it does not remove it.

## PR mechanics (no `verified-pr`)

- Base the PR on the branch the run sheet names; check the base before opening.
- The body says what changed and how to test it. No local file paths in the title, body or comments.
- Nothing is approved, merged or marked ready without the word the run sheet requires (`SKILL.md`, standing rules).
