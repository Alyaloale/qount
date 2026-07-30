"""Backward-compatible imports for the shared research market-data helpers.

New code should import from :mod:`qount.research_data.market_data`.  This module
remains temporarily so archived GRID callers and existing research scripts keep
the same API while their strategy code is retired independently.
"""

from qount.research_data.market_data import DEFAULT_CACHE_DIR
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.market_data import checksum_url
from qount.research_data.market_data import closes
from qount.research_data.market_data import day_url
from qount.research_data.market_data import download_day
from qount.research_data.market_data import download_funding_month
from qount.research_data.market_data import download_month
from qount.research_data.market_data import funding_url
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.research_data.market_data import month_url
from qount.research_data.market_data import parse_checksum_sidecar
from qount.research_data.market_data import parse_funding_csv
from qount.research_data.market_data import parse_funding_zip_bytes
from qount.research_data.market_data import parse_kline_csv
from qount.research_data.market_data import parse_zip_bytes
from qount.research_data.market_data import validate_archive_checksum
from qount.research_data.market_data import verified_archive_fetch
from qount.research_data.market_data import _cached_download

__all__ = [
    "DEFAULT_CACHE_DIR",
    "Bar",
    "Funding",
    "checksum_url",
    "closes",
    "day_url",
    "download_day",
    "download_funding_month",
    "download_month",
    "funding_url",
    "load_funding",
    "load_klines",
    "month_url",
    "parse_checksum_sidecar",
    "parse_funding_csv",
    "parse_funding_zip_bytes",
    "parse_kline_csv",
    "parse_zip_bytes",
    "validate_archive_checksum",
    "verified_archive_fetch",
]
