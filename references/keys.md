# Keys: accounts, spend and secrets

Read this when a worker needs an API key or a paid account, before any paid run, and before publishing anything.
If `keys` is installed, use it; this file is the short version.

## Accounts

- **Check the account, not only that the key works.** A key that returns 200 can belong to the wrong account
  (personal instead of work, or the reverse), and the bill goes there. Ask the provider which account or
  organisation the key belongs to, and compare it with the run sheet.
- **Check a new key with a free call** (list models, or the account endpoint) before it is used for work. A paid
  call is not a test.
- A key pasted in chat goes into the process environment only; never into a file, commit, report or log.

## Spend

- **State a spend cap before each paid run** in the run sheet or the brief: dollars, tokens, or number of calls. A
  run with no cap does not start.
- **Check usage after the run**, from the provider's usage page or API, and include cached tokens: cache reads and
  writes are billed, and a total that leaves them out is too low.
- A quota that is nearly used up goes to new stages; fix rounds use the fallback worker (`SKILL.md`, architect pass, step 8).
- One tiny call per paid account at run start tells you whether it has funds. HTTP 402 or "insufficient" mid-run stops
  that worker, and its stage moves along the approved fallback chain.

## Handling secrets

- **Keys live only in the worker's process environment.** Never on the command line (it shows in process lists and
  shell history), never in a file in the repo, never in a brief or an event line.
- Never edit the owner's `.env`. Set variables in the process that starts the worker, and blank the ones it does not need.
- Never print a key, even partly, in a report; name it by variable name only.

## Before publishing anything (a PR, a repo, a release, a screenshot)

- Search the diff and the files for key prefixes (`sk-`, `ghp_`, `AKIA`, `xox`, long hex or base64 strings) and for
  the values of environment variables you set during the run.
- Search for local paths (a drive letter, `/home/`, `/Users/`), user names, and private project or client names.
- Check screenshots and logs too: a terminal capture shows the environment.
- A found secret is rotated, not just deleted; removing it from a commit leaves it in history.
