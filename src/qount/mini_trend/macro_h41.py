"""Point-in-time Federal Reserve H.4.1 total-assets history."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


H41_CAPACITY_VERSION = "mini_trend_fed_h41_capacity_v0.1"
H41_DATASET_VERSION = "mini_trend_fed_h41_total_assets_v0.1"
H41_ROOT_URL = "https://www.federalreserve.gov/releases/h41"
H41_RELEASE_DATES_URL = f"{H41_ROOT_URL}/releaseDates.json"
FetchBytes = Callable[[str], bytes]
_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b"
)


@dataclass(frozen=True)
class H41CapacityConfig:
    probe_release_dates: tuple[str, ...] = (
        "2021-01-07",
        "2021-03-04",
        "2025-01-02",
    )
    request_timeout_seconds: float = 60.0
    request_retries: int = 3

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "source": "Federal Reserve H.4.1 official historical release archive",
                "target": "Consolidated Statement of Condition / Total assets",
                "strategy_results_evaluated": False,
            }
        )


@dataclass(frozen=True)
class H41DatasetConfig:
    start_release_date: str = "2021-01-07"
    end_release_date: str = "2026-07-16"
    decision_lag_days: int = 1
    minimum_release_coverage: float = 1.0
    request_timeout_seconds: float = 60.0
    request_retries: int = 3

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "source": "Federal Reserve H.4.1 official historical release archive",
                "target": "Consolidated Statement of Condition / Total assets",
                "point_in_time_rule": "decision date equals official release date plus one day",
                "paper_or_live_allowed": False,
            }
        )


class _H41HTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        elif tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None:
            assert self._row is not None
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table_stack:
            self._table_stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())


def _parse_human_date(value: str) -> dt.date:
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported H.4.1 date: {value}")


def parse_release_dates(raw: bytes) -> list[str]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("H.4.1 releaseDates payload must be a list")
    values = []
    for year in payload:
        if not isinstance(year, dict) or not isinstance(year.get("Months"), list):
            raise ValueError("invalid H.4.1 releaseDates year row")
        for month in year["Months"]:
            for raw_date in month.get("Dates", []):
                text = str(raw_date)
                date = dt.datetime.strptime(text, "%Y%m%d").date()
                values.append(date.isoformat())
    if len(values) != len(set(values)):
        raise ValueError("duplicate H.4.1 release date")
    return sorted(values)


def _parse_total_assets(value: str) -> int | None:
    cleaned = value.replace(",", "").strip()
    if not cleaned.isdigit():
        return None
    amount = int(cleaned)
    return amount if amount >= 1_000_000 else None


def parse_h41_text(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    marker = "5. Consolidated Statement of Condition of All Federal Reserve Banks"
    start = text.find(marker)
    if start < 0:
        raise ValueError("legacy H.4.1 text is missing consolidated statement table 5")
    section = text[start:]
    header_dates = _DATE_PATTERN.findall(section[:1_000])
    if not header_dates:
        raise ValueError("legacy H.4.1 text is missing observation date")
    observation_date = _parse_human_date(header_dates[0])
    match = re.search(
        r"^Total assets\s+(?:\(\d+\)\s+)?([\d,]+)(?:\s|$)",
        section,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("legacy H.4.1 text is missing total assets")
    total_assets = _parse_total_assets(match.group(1))
    if total_assets is None:
        raise ValueError("invalid legacy H.4.1 total assets")
    return {
        "format": "legacy_txt",
        "observation_date": observation_date.isoformat(),
        "total_assets_usd_millions": total_assets,
    }


def parse_h41_html(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    parser = _H41HTMLParser()
    parser.feed(text)
    for table in parser.tables:
        header = " ".join(" ".join(row) for row in table[:4])
        if "Assets, liabilities, and capital" not in header:
            continue
        dates = _DATE_PATTERN.findall(header)
        if not dates:
            continue
        for row in table:
            if not row or row[0].strip() != "Total assets":
                continue
            values = [_parse_total_assets(cell) for cell in row[1:]]
            total_assets = next((value for value in values if value is not None), None)
            if total_assets is None:
                continue
            return {
                "format": "modern_html",
                "observation_date": _parse_human_date(dates[0]).isoformat(),
                "total_assets_usd_millions": total_assets,
            }
    raise ValueError("modern H.4.1 HTML is missing consolidated total assets")


def legacy_text_link(raw: bytes) -> str | None:
    parser = _H41HTMLParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return next(
        (href for href in parser.links if href.upper().endswith("H41.TXT")),
        None,
    )


def report_html_link(raw: bytes) -> str | None:
    parser = _H41HTMLParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return next(
        (
            href
            for href in parser.links
            if urllib.parse.urlparse(href).path.lower().endswith("/h41.htm")
            or urllib.parse.urlparse(href).path.lower() == "h41.htm"
        ),
        None,
    )


def _default_fetch(url: str, *, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qount-fed-h41/0.1"}
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _write_cache(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"refusing to overwrite mismatched H.4.1 cache: {path}")
        return
    partial = path.with_name(f"{path.name}.part")
    partial.write_bytes(raw)
    os.replace(partial, path)


def _load(
    url: str,
    path: Path,
    *,
    fetch: FetchBytes,
) -> tuple[bytes, bool]:
    if path.exists():
        return path.read_bytes(), True
    raw = fetch(url)
    _write_cache(path, raw)
    return raw, False


def _release_path(root: Path, release_date: str, filename: str) -> Path:
    date = dt.date.fromisoformat(release_date)
    return root / "releases" / f"{date.year:04d}" / f"{date.month:02d}" / date.isoformat() / filename


def _load_release(
    release_date: str,
    *,
    cache_root: Path,
    fetch: FetchBytes,
) -> dict[str, Any]:
    compact = release_date.replace("-", "")
    page_url = f"{H41_ROOT_URL}/{compact}/"
    page_path = _release_path(cache_root, release_date, "page.html")
    page, page_hit = _load(page_url, page_path, fetch=fetch)
    link = legacy_text_link(page)
    sources = [
        {
            "url": page_url,
            "path": str(page_path),
            "bytes": len(page),
            "sha256": hashlib.sha256(page).hexdigest(),
            "cache_hit": page_hit,
        }
    ]
    if link is not None:
        text_url = urllib.parse.urljoin(page_url, link)
        text_path = _release_path(cache_root, release_date, "H41.TXT")
        source, text_hit = _load(text_url, text_path, fetch=fetch)
        parsed = parse_h41_text(source)
        sources.append(
            {
                "url": text_url,
                "path": str(text_path),
                "bytes": len(source),
                "sha256": hashlib.sha256(source).hexdigest(),
                "cache_hit": text_hit,
            }
        )
        source_layout = "legacy_txt"
    else:
        html_link = report_html_link(page)
        if html_link is not None:
            report_url = urllib.parse.urljoin(page_url, html_link)
            report_path = _release_path(cache_root, release_date, "report.html")
            source, report_hit = _load(report_url, report_path, fetch=fetch)
            parsed = parse_h41_html(source)
            sources.append(
                {
                    "url": report_url,
                    "path": str(report_path),
                    "bytes": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                    "cache_hit": report_hit,
                }
            )
            source_layout = "linked_html"
        else:
            parsed = parse_h41_html(page)
            source_layout = "inline_html"
    release = dt.date.fromisoformat(release_date)
    observation = dt.date.fromisoformat(parsed["observation_date"])
    lag = (release - observation).days
    if lag < 0 or lag > 8:
        raise ValueError(f"invalid H.4.1 observation/release lag for {release_date}: {lag}")
    return {
        "release_date": release_date,
        "observation_date": observation.isoformat(),
        "total_assets_usd_millions": parsed["total_assets_usd_millions"],
        "format": parsed["format"],
        "source_layout": source_layout,
        "observation_to_release_lag_days": lag,
        "sources": sources,
    }


def _fetcher(timeout: float, retries: int, fetch: FetchBytes | None) -> FetchBytes:
    return fetch or (
        lambda url: _default_fetch(url, timeout=timeout, retries=retries)
    )


def build_h41_capacity_audit(
    cache_root: str | Path,
    config: H41CapacityConfig | None = None,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    config = config or H41CapacityConfig()
    actual_fetch = _fetcher(config.request_timeout_seconds, config.request_retries, fetch)
    root = Path(cache_root).expanduser()
    probes = [
        _load_release(date, cache_root=root, fetch=actual_fetch)
        for date in config.probe_release_dates
    ]
    layouts = {row["source_layout"] for row in probes}
    ready = layouts == {"legacy_txt", "linked_html", "inline_html"} and all(
        row["total_assets_usd_millions"] > 1_000_000 for row in probes
    )
    return {
        "schema_version": H41_CAPACITY_VERSION,
        "artifact_type": "mini_trend_fed_h41_source_capacity",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "contract_hash": config.contract_hash,
        },
        "probes": probes,
        "diagnostics": {
            "verdict": "select_fed_h41_total_assets_g0" if ready else "block_macro_g0",
            "all_archive_layouts_parsed": ready,
            "selected_candidate_id": "fed_h41_total_assets_weekly" if ready else None,
            "point_in_time": ready,
            "provider_release_date_available": ready,
            "strategy_results_evaluated": False,
            "paper_or_live_allowed": False,
        },
    }


def _feature_rows(rows: list[dict[str, Any]], decision_lag_days: int) -> list[dict[str, Any]]:
    values = [float(row["total_assets_usd_millions"]) for row in rows]
    features = []
    for index, row in enumerate(rows):
        if index < 13:
            continue
        change_4w = values[index] / values[index - 4] - 1.0
        prior_change_4w = values[index - 4] / values[index - 8] - 1.0
        change_13w = values[index] / values[index - 13] - 1.0
        release = dt.date.fromisoformat(row["release_date"])
        features.append(
            {
                "observation_date": row["observation_date"],
                "release_date": row["release_date"],
                "decision_date": (release + dt.timedelta(days=decision_lag_days)).isoformat(),
                "total_assets_usd_millions": values[index],
                "fed_assets_4w_change_pct": change_4w,
                "fed_assets_13w_change_pct": change_13w,
                "fed_assets_4w_acceleration": change_4w - prior_change_4w,
            }
        )
    return features


def h41_dataset_data_hash(
    *,
    contract_hash: str,
    release_index_sha256: str,
    rows: list[dict[str, Any]],
    features: list[dict[str, Any]],
) -> str:
    sources = [source for row in rows for source in row["sources"]]
    semantic_rows = [
        {
            key: row[key]
            for key in (
                "release_date",
                "observation_date",
                "total_assets_usd_millions",
                "format",
                "source_layout",
                "observation_to_release_lag_days",
            )
        }
        for row in rows
    ]
    return canonical_hash(
        {
            "contract_hash": contract_hash,
            "release_index_sha256": release_index_sha256,
            "source_sha256": [source["sha256"] for source in sources],
            "rows": semantic_rows,
            "features": features,
        }
    )


def build_h41_dataset(
    cache_root: str | Path,
    config: H41DatasetConfig | None = None,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    config = config or H41DatasetConfig()
    start = dt.date.fromisoformat(config.start_release_date)
    end = dt.date.fromisoformat(config.end_release_date)
    if end < start or config.decision_lag_days < 1:
        raise ValueError("invalid H.4.1 dataset date or decision lag")
    root = Path(cache_root).expanduser()
    actual_fetch = _fetcher(config.request_timeout_seconds, config.request_retries, fetch)
    index_path = root / "releaseDates.json"
    index_raw, index_hit = _load(
        H41_RELEASE_DATES_URL, index_path, fetch=actual_fetch
    )
    release_dates = [
        value
        for value in parse_release_dates(index_raw)
        if start <= dt.date.fromisoformat(value) <= end
    ]
    rows = [
        _load_release(value, cache_root=root, fetch=actual_fetch)
        for value in release_dates
    ]
    parsed = {row["release_date"] for row in rows}
    coverage = len(parsed) / len(release_dates) if release_dates else 0.0
    blockers = []
    if not release_dates:
        blockers.append("no_official_release_dates")
    if coverage < config.minimum_release_coverage:
        blockers.append("release_coverage_below_gate")
    observation_dates = [row["observation_date"] for row in rows]
    if len(observation_dates) != len(set(observation_dates)):
        blockers.append("duplicate_observation_date")
    features = _feature_rows(rows, config.decision_lag_days)
    if not features:
        blockers.append("no_macro_features")
    sources = [source for row in rows for source in row["sources"]]
    data_hash = h41_dataset_data_hash(
        contract_hash=config.contract_hash,
        release_index_sha256=hashlib.sha256(index_raw).hexdigest(),
        rows=rows,
        features=features,
    )
    return {
        "schema_version": H41_DATASET_VERSION,
        "artifact_type": "mini_trend_fed_h41_total_assets_dataset",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "public_data_only": True,
            "private_exchange_data": False,
            "point_in_time": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "contract_hash": config.contract_hash,
        },
        "release_index": {
            "url": H41_RELEASE_DATES_URL,
            "path": str(index_path),
            "cache_hit": index_hit,
            "bytes": len(index_raw),
            "sha256": hashlib.sha256(index_raw).hexdigest(),
        },
        "diagnostics": {
            "verdict": "pass_point_in_time_macro_dataset" if not blockers else "block_data",
            "blockers": blockers,
            "official_release_count": len(release_dates),
            "parsed_release_count": len(rows),
            "release_coverage": coverage,
            "legacy_release_count": sum(row["format"] == "legacy_txt" for row in rows),
            "modern_release_count": sum(row["format"] == "modern_html" for row in rows),
            "source_layout_counts": {
                layout: sum(row["source_layout"] == layout for row in rows)
                for layout in ("legacy_txt", "linked_html", "inline_html")
            },
            "feature_rows": len(features),
            "source_file_count": len(sources) + 1,
            "source_bytes": len(index_raw) + sum(source["bytes"] for source in sources),
            "strategy_results_evaluated": False,
            "promotion_evidence": False,
        },
        "weekly_rows": rows,
        "weekly_features": features,
        "data_hash": data_hash,
    }


def write_h41_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-fed-h41",
        path_key="artifact_path",
        default_filename="mini_trend_fed_h41.json",
        explicit_path=explicit_path,
    )
