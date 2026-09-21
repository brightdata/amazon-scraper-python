"""Get Amazon products by ASIN, or by the URL that carries one.

    ASINs -> scrape.amazon.products(urls) -> rows -> matched back by ASIN

Every ASIN asked for goes into one job. The API bills per record, not per job.

Rows are matched to inputs on the row's own `asin`, never on position. With a
list of URLs the SDK pairs rows to inputs by index, and the API returns them in
a different order each run, so the SDK's `ScrapeResult.url` can name one
product while `data` holds another (sdk-python#60).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brightdata import SyncBrightDataClient

#: Seconds, the SDK's own unit and its default for Amazon. The Node twin counts in ms.
TIMEOUT = 240

#: Which Amazon site the ASINs are read from.
DOMAIN = "https://www.amazon.com"

_ASIN = re.compile(r"^[A-Z0-9]{10}$", re.I)
_ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I)


def clean_asin(value: str) -> str:
    """Accept B0CRMZHDG8, a /dp/ URL, a /gp/product/ URL, or one with a query."""
    raw = (value or "").strip()
    found = _ASIN_IN_PATH.search(raw)
    candidate = found.group(1) if found else raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not _ASIN.match(candidate):
        raise ValueError(f"{value!r} is not an Amazon ASIN")
    return candidate.upper()


def product_url(value: str) -> str:
    return f"{DOMAIN}/dp/{clean_asin(value)}"


def rows(result: Any) -> list[dict[str, Any]]:
    """Flatten a ScrapeResult, or a list of them, into plain dicts."""
    if isinstance(result, list):
        return [row for item in result for row in rows(item)]
    data = getattr(result, "data", result)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def envelope_error(result: Any) -> str | None:
    """A failed or timed out request carries no rows to explain itself.

    On failure the SDK returns one ScrapeResult even for list input, so this is
    the only shape that can say the whole job died.
    """
    if isinstance(result, list) or getattr(result, "success", True):
        return None
    return str(getattr(result, "error", None) or getattr(result, "status", "request failed"))


def row_asin(row: dict[str, Any]) -> str:
    """The ASIN a row answers for: its asin field, else the one in its URL."""
    direct = row.get("asin")
    if isinstance(direct, str) and _ASIN.match(direct):
        return direct.upper()
    source = row.get("input_url") or (row.get("input") or {}).get("url") or row.get("url") or ""
    found = _ASIN_IN_PATH.search(str(source))
    return found.group(1).upper() if found else ""


@dataclass
class Outcome:
    """What happened to one ASIN."""

    asin: str
    product: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def line(self) -> str:
        """One line a reader can understand without having read the source."""
        if not self.ok:
            return f"failed  {self.asin}: {self.error}"
        title = str((self.product or {}).get("title") or "")[:48]
        suffix = f" ({title})" if title else ""
        return f"got     {self.asin}: {len(self.product or {})} fields{suffix}"


def attribute(asins: list[str], found: list[dict[str, Any]]) -> list[Outcome]:
    """Match each row to the ASIN that asked for it, by the row's own identity."""
    by_asin: dict[str, dict[str, Any]] = {}
    for row in found:
        asin = row_asin(row)
        if asin in asins and asin not in by_asin:
            by_asin[asin] = row

    outcomes = []
    for asin in asins:
        row = by_asin.get(asin)
        if row is None:
            outcomes.append(Outcome(asin, error="the API returned no row for this ASIN"))
        elif row.get("error"):
            outcomes.append(Outcome(asin, error=str(row["error"])))
        else:
            outcomes.append(Outcome(asin, product=row))
    return outcomes


def client_context(client: Any = None) -> Any:
    """The client passed in, or one we open and own.

    SyncBrightDataClient builds its event loop in __enter__, so it must be
    entered. An unentered client fails with an AttributeError about
    run_until_complete.
    """
    # auto_create_zones defaults to True: the SDK tries to create Web Unlocker
    # and SERP zones on startup, which this scraper never uses. Creating a zone
    # needs a payment method, so leaving it on breaks the first run for free
    # accounts.
    return nullcontext(client) if client is not None else SyncBrightDataClient(
        auto_create_zones=False
    )


def fetch(client: Any, asins: list[str], timeout: int = TIMEOUT) -> list[Outcome]:
    """One job for every ASIN. Never raises: a failure becomes Outcomes."""
    if not asins:
        return []
    try:
        # A list, even of one, so the SDK never collapses the answer to a dict.
        result = client.scrape.amazon.products([f"{DOMAIN}/dp/{a}" for a in asins], timeout=timeout)
        failed = envelope_error(result)
        if failed:
            return [Outcome(asin, error=failed) for asin in asins]
        return attribute(asins, rows(result))
    except Exception as exc:  # one bad batch must not end the run with a traceback
        return [Outcome(asin, error=f"{type(exc).__name__}: {exc}") for asin in asins]


def scrape(values: Iterable[str], client: Any = None) -> list[Outcome]:
    """One Outcome per input, in the order asked. A repeated ASIN is fetched once."""
    values = list(values)
    asins: list[str] = []
    rejected: dict[str, Outcome] = {}
    for value in values:
        try:
            asins.append(clean_asin(value))
        except ValueError as exc:
            rejected[str(value)] = Outcome(str(value), error=str(exc))

    found: dict[str, Outcome] = {}
    if asins:
        with client_context(client) as opened:
            found = {o.asin: o for o in fetch(opened, list(dict.fromkeys(asins)))}

    return [rejected[str(v)] if str(v) in rejected else found[clean_asin(v)] for v in values]


def write(outcomes: list[Outcome], path: str | Path) -> Path:
    """Write one JSON file: when it ran, and the product found per ASIN."""
    document = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": [{"asin": o.asin, "product": o.product} for o in outcomes],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return target
