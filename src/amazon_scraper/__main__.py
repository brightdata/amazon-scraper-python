"""amazon-scraper B0CRMZHDG8 B085DVHQ57, or python -m amazon_scraper ..."""

from __future__ import annotations

import argparse
import sys

from brightdata import BrightDataError
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .scrape import Outcome, clean_asin, client_context, fetch, write

#: The SDK's own advice lists a Python parameter. A command has no such thing.
NO_TOKEN = (
    "API token required but not found.\n"
    "  export BRIGHTDATA_API_TOKEN=YOUR_API_KEY   token: https://brightdata.com/cp/setting/users\n"
    "  or run once: npx -p @brightdata/cli bdata login"
)

#: A spinner and a running clock, so a minute of waiting looks alive.
WAITING = (SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amazon-scraper",
        description="Scrape Amazon products by ASIN, or by a product URL carrying one.",
    )
    parser.add_argument("asins", nargs="+", help="ASINs such as B0CRMZHDG8, or product URLs")
    parser.add_argument("--out", default="amazon.json", help="output file, default %(default)s")
    args = parser.parse_args(argv)

    count = len(args.asins)
    plural = "" if count == 1 else "s"
    print(
        f"Fetching {count} Amazon product{plural}: {', '.join(args.asins)}\n"
        "One job for all of them. One credit per product.",
        flush=True,  # piped, an unflushed header would print after the error below
    )

    asins, outcomes_by_input = [], {}
    for value in args.asins:
        try:
            asins.append(clean_asin(value))
        except ValueError as exc:
            outcomes_by_input[value] = str(exc)

    found = {}
    try:
        with client_context() as client, Progress(*WAITING, transient=True) as bar:
            label = f"{len(asins)} product{'' if len(asins) == 1 else 's'}"
            if not bar.console.is_terminal:
                print(f"asking  {label}...", flush=True)  # a log wants a line, not a spinner
            task = bar.add_task(label)
            for outcome in fetch(client, list(dict.fromkeys(asins))):
                found[outcome.asin] = outcome
            bar.remove_task(task)
    except BrightDataError as exc:
        # Almost always a missing token, which reads as a crash under a traceback.
        print(NO_TOKEN if "token required" in str(exc) else exc, file=sys.stderr)
        return 2

    outcomes = []
    for value in args.asins:
        if value in outcomes_by_input:
            outcomes.append(Outcome(value, error=outcomes_by_input[value]))
        else:
            outcomes.append(found[clean_asin(value)])
    for outcome in outcomes:
        print(outcome.line())

    path = write(outcomes, args.out)
    got = sum(1 for o in outcomes if o.ok)
    print(f"\nSaved {got} of {len(outcomes)} products as JSON to {path}")
    return 0 if all(o.ok for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
