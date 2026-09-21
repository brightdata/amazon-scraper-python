"""These run without a token. The client is a stub."""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from brightdata import BrightDataError

import amazon_scraper.__main__  # noqa: F401  (registers the module for monkeypatching)
from amazon_scraper.scrape import attribute, clean_asin, product_url, row_asin, scrape, write

ROOT = Path(__file__).resolve().parents[1]
STANLEY, OWALA, DEAD = "B0CRMZHDG8", "B085DVHQ57", "B0ZZZZZZZZ"


def url(asin):
    return f"https://www.amazon.com/dp/{asin}"


def stub(answer, calls=None):
    """A client whose one Amazon call returns canned results."""

    def products(urls, **kwargs):
        if calls is not None:
            calls.append({"urls": urls, **kwargs})
        if isinstance(answer, Exception):
            raise answer
        return answer

    return SimpleNamespace(scrape=SimpleNamespace(amazon=SimpleNamespace(products=products)))


def result(data, **fields):
    return SimpleNamespace(data=data, success=fields.pop("success", True), **fields)


def test_an_asin_a_dp_url_a_gp_product_url_and_lower_case_name_the_same_product():
    assert clean_asin(STANLEY) == STANLEY
    assert clean_asin(STANLEY.lower()) == STANLEY
    assert clean_asin(f"https://www.amazon.com/Quencher/dp/{STANLEY}?th=1") == STANLEY
    assert clean_asin(f"https://www.amazon.com/gp/product/{OWALA}/") == OWALA
    assert product_url(STANLEY) == url(STANLEY)


def test_anything_that_is_not_an_asin_is_refused_before_any_request():
    for bad in ("not-an-asin", "", "B0CRMZHDG", "https://www.amazon.com/"):
        with pytest.raises(ValueError, match="is not an Amazon ASIN"):
            clean_asin(bad)


def test_rows_are_matched_by_their_own_asin_not_by_position():
    """The SDK pairs results with URLs by index and the API reorders rows (sdk-python#60).

    Here the result labelled STANLEY holds OWALA's product, and the reverse.
    Trusting ScrapeResult.url would swap them.
    """
    mislabelled = [
        result({"asin": OWALA, "title": "Owala FreeSip"}, url=url(STANLEY)),
        result({"asin": STANLEY, "title": "STANLEY Quencher"}, url=url(OWALA)),
    ]
    stanley, owala = scrape([STANLEY, OWALA], client=stub(mislabelled))

    assert stanley.product["title"] == "STANLEY Quencher"
    assert owala.product["title"] == "Owala FreeSip"


def test_row_asin_reads_the_asin_field_then_the_url_and_is_case_insensitive():
    assert row_asin({"asin": STANLEY.lower()}) == STANLEY
    assert row_asin({"input_url": url(OWALA)}) == OWALA
    assert row_asin({"input": {"url": url(DEAD)}, "error": "x"}) == DEAD
    assert row_asin({"title": "no identifier at all"}) == ""


def test_an_error_row_fails_only_the_asin_it_belongs_to():
    rows = [
        {"asin": STANLEY, "title": "STANLEY Quencher"},
        {
            "input": {"url": url(DEAD)},
            "error": "The navigation resulted in a dead page (404 status code)",
        },
    ]
    good, bad = attribute([STANLEY, DEAD], rows)

    assert good.ok
    assert bad.line() == f"failed  {DEAD}: The navigation resulted in a dead page (404 status code)"


def test_an_asin_the_api_never_returned_is_a_failure_not_a_silent_gap():
    """zip() in the SDK stops at the shorter list, so a missing row just vanishes."""
    [only] = scrape([STANLEY], client=stub([]))

    assert not only.ok
    assert "no row" in only.error


def test_a_timed_out_request_fails_every_asin_in_the_batch():
    """On failure the SDK returns one result, not a list, even for list input."""
    timed_out = result(None, success=False, error=None, status="timeout")
    outcomes = scrape([STANLEY, OWALA], client=stub(timed_out))

    assert [o.error for o in outcomes] == ["timeout", "timeout"]


def test_one_bad_input_does_not_stop_the_others_being_fetched():
    good, bad = scrape([STANLEY, "not-an-asin"], client=stub([result({"asin": STANLEY})]))

    assert good.ok
    assert not bad.ok and "is not an Amazon ASIN" in bad.error


def test_a_raised_request_does_not_end_the_run():
    [outcome] = scrape([STANLEY], client=stub(RuntimeError("boom")))

    assert outcome.error == "RuntimeError: boom"


def test_every_asin_goes_in_one_job_as_a_dp_url():
    calls = []
    scrape([STANLEY, f"https://www.amazon.com/gp/product/{OWALA}"], client=stub([], calls))

    assert len(calls) == 1, "a batch must be one job, not one job per ASIN"
    assert calls[0]["urls"] == [url(STANLEY), url(OWALA)]


def test_the_same_asin_twice_is_fetched_once_and_answered_twice():
    calls = []
    outcomes = scrape([STANLEY, url(STANLEY)], client=stub([result({"asin": STANLEY})], calls))

    assert calls[0]["urls"] == [url(STANLEY)], "a duplicate ASIN must not be billed twice"
    assert len(outcomes) == 2 and all(o.ok for o in outcomes)


def test_a_run_writes_what_it_found(tmp_path):
    product = {"asin": STANLEY, "title": "STANLEY Quencher"}
    outcomes = scrape([STANLEY], client=stub([result(product)]))

    assert outcomes[0].line() == f"got     {STANLEY}: 2 fields (STANLEY Quencher)"

    path = write(outcomes, tmp_path / "out.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["products"] == [{"asin": STANLEY, "product": product}]
    assert document["generated_at"]


def test_a_client_we_own_gets_entered(monkeypatch):
    """SyncBrightDataClient is unusable until __enter__ builds its event loop."""
    entered = []

    class Fake:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            entered.append(True)
            return stub([result({"asin": STANLEY})])

        def __exit__(self, *exc):
            entered.append(False)
            return False

    monkeypatch.setattr(sys.modules["amazon_scraper.scrape"], "SyncBrightDataClient", Fake)
    assert scrape([STANLEY])[0].ok
    assert entered == [True, False]


def test_we_do_not_ask_the_sdk_to_create_zones(monkeypatch):
    """Zone creation needs a payment method and this scraper never uses a zone."""
    seen = {}

    class Fake:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return stub([])

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(sys.modules["amazon_scraper.scrape"], "SyncBrightDataClient", Fake)
    scrape([STANLEY])
    assert seen.get("auto_create_zones") is False


def fake_cli(monkeypatch, answer):
    cli = sys.modules["amazon_scraper.__main__"]
    monkeypatch.setattr(cli, "client_context", lambda: nullcontext(stub(answer)))
    return cli


def test_the_cli_exit_code_says_whether_every_asin_worked(monkeypatch, tmp_path):
    cli = fake_cli(monkeypatch, [result({"asin": STANLEY, "title": "t"})])
    assert cli.main([STANLEY, "--out", str(tmp_path / "ok.json")]) == 0

    cli = fake_cli(monkeypatch, [result({"input": {"url": url(STANLEY)}, "error": "boom"})])
    assert cli.main([STANLEY, "--out", str(tmp_path / "bad.json")]) == 1


def test_no_asin_is_refused_before_any_request(capsys):
    cli = sys.modules["amazon_scraper.__main__"]
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2
    assert "usage: amazon-scraper" in capsys.readouterr().err


def test_a_missing_token_is_a_message_not_a_traceback(monkeypatch, capsys):
    cli = sys.modules["amazon_scraper.__main__"]

    def no_token():
        raise BrightDataError("API token required but not found.")

    monkeypatch.setattr(cli, "client_context", no_token)
    assert cli.main([STANLEY]) == 2
    err = capsys.readouterr().err
    assert "export BRIGHTDATA_API_TOKEN" in err and "bdata login" in err


def test_piped_output_keeps_the_header_before_the_error(tmp_path):
    """A log or an agent reads a pipe. The header must not land after the error."""
    tokens = ("BRIGHTDATA_API_TOKEN", "BRIGHTDATA_API_KEY")
    env = {k: v for k, v in os.environ.items() if k not in tokens}
    env["HOME"] = str(tmp_path)  # no CLI login, no .env: the stranger's machine
    run = subprocess.run(
        [sys.executable, "-m", "amazon_scraper", STANLEY],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    assert run.returncode == 2, run.stdout
    assert run.stdout.index("Fetching 1 Amazon product") < run.stdout.index("API token required")


def _executable(func):
    """A function's body, past its docstring, with comments stripped.

    The docstring documents numOfReviews, and a comment names it too. Neither is
    use, so both are cut before looking for the parameter in the code.
    """
    source = inspect.getsource(func)
    first = source.index('"""')
    body = source[source.index('"""', first + 3) + 3 :]
    return "\n".join(line.split("#")[0] for line in body.splitlines())


def test_the_sdk_contract_the_readme_relies_on():
    """Offline, no token. Every claim the README makes about the SDK, pinned here."""
    from brightdata.scrapers import workflow
    from brightdata.scrapers.amazon.scraper import AmazonScraper
    from brightdata.scrapers.amazon.search import AmazonSearchScraper

    for name in ("products", "reviews", "sellers"):
        for suffix in ("", "_trigger", "_status", "_fetch"):
            assert callable(getattr(AmazonScraper, name + suffix, None)), name + suffix

    # The products dataset is the one the control panel shows.
    assert AmazonScraper.DATASET_ID == "gd_l7q7dkf244hwjntr0"

    # Timeouts are seconds, 240 by default for Amazon. The Node twin counts milliseconds.
    assert inspect.signature(AmazonScraper.products).parameters["timeout"].default == 240

    # Keyword search exists, on the product-search dataset, with no row cap.
    params = inspect.signature(AmazonSearchScraper.products).parameters
    assert "keyword" in params
    assert not any("limit" in p or "pages" in p for p in params), params

    # There is no discovery by keyword, category, best sellers or UPC on the
    # products dataset. The Node twin has all four.
    for name in ("discover_by_keyword", "discover_by_category", "discover_by_upc", "best_sellers"):
        assert not hasattr(AmazonScraper, name), name

    # Error rows arrive only because the SDK asks for them.
    executor = next(c for c in vars(workflow).values() if hasattr(c, "execute"))
    assert inspect.signature(executor.execute).parameters["include_errors"].default is True


def test_reviews_accepts_a_cap_and_never_sends_it():
    """sdk-python#62. reviews(numOfReviews=20) bills every review the product has.

    The parameter is in the signature and absent from the executable body. This
    is why the README never runs reviews. When the SDK starts sending it, this
    fails, and the README can run a capped reviews example.
    """
    from brightdata.scrapers.amazon.scraper import AmazonScraper

    assert "numOfReviews" in inspect.signature(AmazonScraper.reviews).parameters
    body = _executable(AmazonScraper.reviews)
    for cap in ("numOfReviews", "pastDays", "keyWord"):
        assert cap not in body, f"{cap} is now used: revisit the README's reviews section"


def test_the_readme_excerpt_is_the_start_of_the_example_file():
    sample = (ROOT / "examples" / "sample_output.json").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "\n".join(sample.splitlines()[:19]) in readme, "README excerpt drifted from the file"
    assert "](examples/sample_output.json)" in readme


def test_every_in_page_link_has_its_heading():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = re.findall(r"^#{1,6} (.+)$", readme, re.M)
    anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings}
    for anchor in re.findall(r"\]\(#([^)]+)\)", readme):
        assert anchor in anchors, f"#{anchor} points at no heading"


def test_no_runnable_block_calls_reviews_which_cannot_be_capped():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for code in re.findall(r"```python\n(.*?)```", readme, re.S):
        assert "reviews(" not in code, (
            "a reviews call in a runnable block bills one credit per review, every week"
        )
