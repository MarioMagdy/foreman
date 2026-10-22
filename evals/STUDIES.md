# Version studies

Before a foreman version deploys, run it against the deployed one on the same inputs and keep the evidence here:
one folder per study with `data.json` (every number), `cases/` (inputs), `runs/` (each run's files, redacted by
`python evals/study.py save`), `REPORT.md` and `report.html`. Criteria are written into `data.json` and committed
before the runs start.

| Date | Study | Versions | Cases | Verdict |
|---|---|---|---|---|
| 2026-10-22 | [gates-vs-v2.1](studies/2026-10-22-gates-vs-v2.1/) | v2.1 (5479d9f) vs v2.2 candidate (11cb4d9) | two private projects | v2.2 better in both cases (judge rank 1.5 vs 3.5, criteria 13/14 vs 8/14); ship after 3 fixes |
