# Contributing

The most useful thing you can send us is a broken example.

## Report a bug

[Open an issue](https://github.com/brightdata/amazon-scraper-python/issues) and include:

- the command or the snippet you ran
- what you expected, and what happened instead
- your versions: `python --version` and `pip show brightdata-sdk`

Paste the error text rather than a screenshot of it. Never paste your API
token, in an issue or anywhere else.

Questions about the API, your account or your credits go to
[Bright Data support](https://brightdata.zendesk.com/hc/en-us/requests/new).
We cannot see your account from here.

## Send a pull request

Small fixes need no permission. For anything larger, open an issue first, so
that nobody writes the same code twice.

Before you push, check that:

- `pytest` passes offline, with no token set
- `ruff check .` is clean
- every fenced block in the README still runs exactly as pasted

## What this repo will not take

It stays small on purpose: 15 files and about 300 lines of Python. Read
[AGENTS.md](AGENTS.md) first. It lists what is missing here deliberately,
including retries, deduplication, scheduling, databases and concurrency.

The outputs in the README come from real runs, and a scheduled job reruns them
against the live API. Do not edit those blocks, the field table or the
"last verified" badge by hand.
