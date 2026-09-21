"""An Amazon scraper on Bright Data's Scraper API."""

from .scrape import Outcome, attribute, clean_asin, product_url, row_asin, rows, scrape, write

__all__ = [
    "Outcome",
    "attribute",
    "clean_asin",
    "product_url",
    "row_asin",
    "rows",
    "scrape",
    "write",
]
__version__ = "0.1.0"
