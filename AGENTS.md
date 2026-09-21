# For coding agents working in this repository

Read this before changing anything. Every line below was verified against the
live API or the installed SDK, `brightdata-sdk` 2.5.2, on 2026-09-21.

## The one that costs money

Reviews bill one credit per review, and **this SDK's cap does nothing**.

`reviews(url, pastDays=None, keyWord=None, numOfReviews=None, timeout=240)`
accepts all three and sends none of them. The request is built from the URL
alone:

    # Note: pastDays, keyWord, numOfReviews are not supported by the API
    payload = [{"url": u} for u in url_list]

That comment is wrong. `GET /datasets/v3/scrapers?domain=amazon.com` lists
`max_reviews` as an input to the reviews scraper, and Bright Data's own sample
input sets it to 20. The SDK does not map `numOfReviews` onto it.

So `reviews(url, numOfReviews=20)` asks for every review and gives no warning.
`B0CRMZHDG8` reports 205,036 reviews. That is one call.

Tracked in [sdk-python#62](https://github.com/brightdata/sdk-python/issues/62).
A test fails the day the SDK starts sending the parameter. Until then no README
block may call `reviews`, and another test enforces that.

The JavaScript SDK has the same gap but fails loudly, rejecting `max_reviews`
with "Unrecognized key" (sdk-js#37). Here the cap is accepted and dropped.

## Auth

- The SDK reads `BRIGHTDATA_API_TOKEN` from the environment, from a `.env` file
  found by searching upward from its own install folder (so the project root,
  when the virtualenv is inside the project), or from the Bright Data CLI login.
  The JavaScript twin does not read `.env`; do not copy its wording here.
- Always `SyncBrightDataClient(auto_create_zones=False)`. Zone creation needs a
  payment method and this repository never uses a zone.

## How the API behaves

- `timeout` is seconds, 240 by default for Amazon. The Node twin's
  `pollTimeout` is milliseconds.
- There is a second timeout: `SyncBrightDataClient(timeout=30)` bounds each HTTP
  request, including downloading a finished snapshot. "Failed to fetch results:
  Request timeout after 30 seconds" is that one, and raising the call's
  `timeout` does not help.
- `products` takes a URL, not an ASIN. `product_url()` writes a `/dp/` URL.
- The products dataset is `gd_l7q7dkf244hwjntr0`, the id the control panel
  shows. It has 119 fields; a product carries 99 or 100 of them.
- A dead ASIN comes back as a row whose error reads "The navigation resulted in
  a dead page (404 status code)". Match the message, not a code.
- A list of URLs is one job. The API bills per record, not per job.

### The SDK mislabels list results

With a list of URLs, `_scrape_urls` pairs rows with inputs by position:

    for url_item, data_item in zip(url_list, result.data):
        ScrapeResult(success=True, data=data_item, url=url_item, ...)

The API returns rows in a different order on each run.

- Never read `ScrapeResult.url` on list input. `attribute()` matches each row to
  its ASIN by the row's own `asin`, falling back to the ASIN inside `input_url`,
  `input["url"]` or `url`.
- `success` is always `True` on list results, error rows included. Read the row.
- On failure or timeout the method returns one `ScrapeResult`, not a list.
- Tracked in [sdk-python#60](https://github.com/brightdata/sdk-python/issues/60).

## What this SDK does not have

- No discovery of full product records by keyword, category URL, best sellers
  URL or UPC. The API has all four and the JavaScript SDK exposes them.
- `client.search.amazon.products(keyword=...)` exists, but it reads the product
  search dataset `gd_lwdb4vjm1ehb499uxs`: search-result rows of about 30 fields,
  not product records. It has no parameter that caps rows and does not send
  `pages_to_search`, so the README documents it and does not run it.
- Nothing reaches the products global dataset `gd_lwhideng15g8jg63s7`, which is
  where discovery by seller, by brand, and by other Amazon domains lives.

## The schema

- Never hardcode a field list.
- The API marks `seller_name`, `zipcode` and `coupon` as `pii: true`. The
  sellers dataset also marks `email` and `seller_phone_number`.
- `get_metadata()` drops that flag: each `DatasetField` keeps only `type`,
  `active`, `required` and `description`. Read the raw endpoint,
  `https://api.brightdata.com/datasets/gd_l7q7dkf244hwjntr0/metadata`, as the
  field-table step in `live.yml` does. Tracked in
  [sdk-python#61](https://github.com/brightdata/sdk-python/issues/61).
- The full documentation index: https://docs.brightdata.com/llms.txt

## The API stalls in waves, and throttles bursts

- Some hours most jobs sit until the poll deadline and return `timeout`. A red
  live check whose only symptom is timeouts is probably that: rerun it.
- Many requests at once from one account return "Your system is sending too many
  of this type of request". Valid inputs fail with it. It clears after a wait.
- That is why the scheduled runs across the scraper repositories are staggered,
  06:00 to 07:20 UTC, and why the README matrix runs three at a time.

## Working here

- `pytest` runs offline and needs no token. `ruff check .` must pass.
- CI installs from the README's own commands on an empty machine. A weekly
  workflow executes every fenced block in the README against the real API.
- The field table and the "last verified" badge are rewritten by the daily run.
  Do not edit either by hand.
- Keep it small: 14 files and about 300 lines of Python. Do not add retries,
  deduplication, scheduling, databases, async examples or concurrency.
