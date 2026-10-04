"""Acquire and classify a new immutable public-data vintage on the external disk.

This task supplements source evidence. It neither rewrites P2/M1 nor trains a
model, and never upgrades retrospective history to historical point-in-time data.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree.ElementTree import ParseError as ETParseError

from .artifacts import (EXTERNAL_ROOT, GUARDS, finish_manifest, new_directory,
                        read_json, safe_member, sha256, utc_now, verify_files, write_json)
from .contracts import cost_contract
from .data import _series, load_public_panel
from .data_sources import (compare_sessions, equity_calendar, parse_invesco,
                           parse_ishares, parse_ssga, reconcile_events, source_text,
                           unique_events)

PUBLIC_HOSTS = frozenset({"www.ishares.com", "www.ssga.com", "www.invesco.com",
                         "dng-api.invesco.com", "www.nyse.com", "ir.theice.com",
                         "www.nasdaqtrader.com", "www.finra.org", "www.govinfo.gov",
                         "www.sec.gov", "www.spdrgoldshares.com"})


@dataclass(frozen=True)
class Source:
    source_id: str
    category: str
    url: str
    suffix: str = ".html"
    parser: str = "reference"
    symbol: str = ""
    review: str = "primary_official_reference"


def public_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in PUBLIC_HOSTS or parts.port not in {None, 443}:
        raise ValueError("public HTTPS allowlist required")
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise ValueError("credentials or fragments are forbidden in source URLs")
    if any(key.lower() in {"apikey", "api_key", "token", "access_token", "key", "password"}
           for key, _ in urllib.parse.parse_qsl(parts.query)):
        raise ValueError("credential-like query parameter is forbidden")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def import_cached_source(source: Source, root: Path, cache: Path, prior: dict,
                         cache_manifest_sha256: str) -> dict | None:
    if prior.get("url") != source.url or prior.get("fetch_status") != "success":
        return None
    public_url(prior["final_url"])
    original = safe_member(cache, prior["file"])
    if sha256(original) != prior["sha256"]:
        raise ValueError("immutable cached source hash mismatch")
    destination = root / "raw" / source.category / (source.source_id + source.suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with original.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    return asdict(source) | GUARDS | {
        "fetch_status": "success", "normalization_status": "not_run", "file": str(destination.relative_to(root)),
        "sha256": sha256(destination), "bytes": destination.stat().st_size,
        "observed_at": prior["observed_at"], "final_url": prior["final_url"],
        "content_type": prior.get("content_type", ""), "historical_asof_verified": False,
        "availability_class": "retrospective_snapshot", "acquisition_method": "verified_immutable_cache_import",
        "imported_at": utc_now(), "cache_root": str(cache), "cache_manifest_sha256": cache_manifest_sha256}


def fetch_source(source: Source, root: Path, *, cache=None, prior=None, cache_hash=None) -> dict:
    public_url(source.url)
    if cache is not None and prior is not None:
        imported = import_cached_source(source, root, cache, prior, cache_hash)
        if imported is not None:
            return imported
    destination = root / "raw" / source.category / (source.source_id + source.suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt = asdict(source) | GUARDS | {"requested_at": utc_now(),
        "historical_asof_verified": False, "availability_class": "retrospective_snapshot",
        "fetch_status": "failed", "normalization_status": "not_run"}
    for attempt in range(2):
        try:
            request = urllib.request.Request(source.url, headers={"User-Agent": "qount-public-research/1.0"})
            with urllib.request.build_opener(PublicRedirect()).open(request, timeout=25) as response:
                public_url(response.url)
                content = response.read(12_000_001)
                if len(content) > 12_000_000:
                    raise ValueError("source exceeds bounded public response size")
                receipt.update({"http_status": response.status, "final_url": response.url,
                                "content_type": response.headers.get("Content-Type", ""),
                                "observed_at": utc_now()})
            if source.suffix == ".pdf" and not content.startswith(b"%PDF"):
                raise ValueError("PDF source returned a different document type")
            if source.suffix == ".xlsx" and not content.startswith(b"PK"):
                raise ValueError("workbook source returned a different document type")
            with destination.open("xb") as stream:
                stream.write(content)
            receipt.update({"fetch_status": "success", "bytes": len(content),
                            "file": str(destination.relative_to(root)), "sha256": sha256(destination),
                            "attempts": attempt + 1})
            receipt.pop("error_class", None)
            return receipt
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            # Never serialize exception text, request headers, proxies or environment values.
            receipt.update({"error_class": type(error).__name__, "attempts": attempt + 1,
                            "http_status": getattr(error, "code", None)})
            if isinstance(error, (urllib.error.HTTPError, ValueError, FileExistsError)):
                break
    return receipt


SEC_PREFIX = "https://www.sec.gov/newsroom/press-releases/"
# Actual transaction-fee changes, excluding Section 6(b) filing fees and
# conditional appropriation announcements. Each rate is USD per million sales.
SEC_RATES = (
    ("2008-04-01", 5.60, "2008-25-fee-rate-advisory-7-fiscal-year-2008", "April 1, 2008"),
    ("2009-04-10", 25.70, "2009-56-fee-rate-advisory-5-fiscal-year-2009", "April 10, 2009"),
    ("2010-01-15", 12.70, "2009-270-fee-rate-advisory-4-fiscal-year-2010", "Jan. 15, 2010"),
    ("2010-04-01", 16.90, "2010-29-fee-rate-advisory-5-fiscal-year-2010", "April 1, 2010"),
    ("2011-01-21", 19.20, "2010-255-fee-rate-advisory-5-fiscal-year-2011", "Jan. 21, 2011"),
    ("2012-02-21", 18.00, "2012-2012-15htm", "February 21, 2012"),
    ("2012-04-01", 22.40, "2012-2012-35htm", "April 1, 2012"),
    ("2013-05-25", 17.40, "2013-2013-74htm", "May 25, 2013"),
    ("2014-03-18", 22.10, "2014-30", "March 18, 2014"),
    ("2015-02-14", 18.40, "2015-8", "Feb. 14, 2015"),
    ("2016-02-16", 21.80, "2016-2", "Feb. 16, 2016"),
    ("2017-07-04", 23.10, "2017-111", "July 4, 2017"),
    ("2018-05-22", 13.00, "2018-67", "May 22, 2018"),
    ("2019-04-16", 20.70, "2019-30", "April 16, 2019"),
    ("2020-02-18", 22.10, "2020-7", "Feb. 18, 2020"),
    ("2021-02-25", 5.10, "2021-8", "February 25, 2021"),
    ("2022-05-14", 22.90, "2022-60", "May 14, 2022"),
    ("2023-02-27", 8.00, "2023-15", "February 27, 2023"),
    ("2024-05-22", 27.80, "2024-2", "May 22, 2024"),
    ("2025-05-14", 0.00, "2025-2", "May 14, 2025"),
    ("2026-04-04", 20.60, "2026-2", "April 4, 2026"),
)
TAF_RATES = (
    ("2009-01-02", .000075, 3.75, "finra_11_27", "earlier_rate_continuity_inferred_from_2011_notice"),
    ("2011-07-01", .000090, 4.50, "finra_11_27", "official_effective_date"),
    ("2012-03-01", .000095, 4.75, "finra_12_06", "official_effective_date"),
    ("2012-07-01", .000119, 5.95, "finra_12_31", "official_effective_date"),
    ("2022-01-01", .000130, 6.49, "finra_2020_schedule", "official_immediately_effective_filing; phased_annual_implementation"),
    ("2023-01-01", .000145, 7.27, "finra_2020_schedule", "official_immediately_effective_filing; phased_annual_implementation"),
    ("2024-01-01", .000166, 8.30, "finra_2020_schedule", "official_immediately_effective_filing; phased_annual_implementation"),
    ("2026-01-01", .000195, 9.79, "finra_2024_schedule", "official_immediately_effective_filing; phased_annual_implementation"),
    ("2026-10-01", 0.0, 0.0, "finra_2026_waiver", "official_temporary_Q4_2026_pause; do_not_extrapolate_past_2026"),
)


def source_plan() -> list[Source]:
    sources = [Source("ssga_distributions", "distributions",
                      "https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx",
                      ".xlsx", "ssga")]
    for symbol, product, slug in (
        ("IWM", "239710", "ishares-russell-2000-etf"),
        ("EFA", "239623", "ishares-msci-eafe-etf"),
        ("EEM", "239637", "ishares-msci-emerging-markets-etf"),
        ("IEF", "239456", "ishares-7-10-year-treasury-bond-etf"),
        ("TLT", "239454", "ishares-20-year-treasury-bond-etf")):
        sources.append(Source("ishares_" + symbol, "distributions",
                              f"https://www.ishares.com/us/products/{product}/{slug}", parser="ishares", symbol=symbol))
    for symbol, cusip in (("QQQ", "46090E103"), ("DBC", "46138B103")):
        sources.append(Source("invesco_" + symbol, "distributions",
                              f"https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{cusip}/distribution?idType=cusip&productType=ETF",
                              ".json", "invesco", symbol))
    sources.extend([
        Source("gld_policy", "distributions", "https://www.ssga.com/us/en/individual/etfs/spdr-gold-shares-gld", parser="gld_policy", symbol="GLD"),
        Source("nyse_calendar_2026", "calendar", "https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf", ".pdf"),
        Source("nyse_juneteenth", "calendar", "https://www.nyse.com/publicdocs/nyse/markets/nyse-american/rule-filings/filings/2021/SR-NYSEAmer-2021-39.pdf", ".pdf"),
        Source("nyse_bush", "calendar", "https://ir.theice.com/press/news-details/2018/New-York-Stock-Exchange-to-Honor-President-George-H-W-Bush/default.aspx"),
        Source("nasdaq_sandy29", "calendar", "https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-44"),
        Source("nasdaq_sandy30", "calendar", "https://www.nasdaqtrader.com/TraderNews.aspx?id=mfqsnews2012-003"),
        Source("nasdaq_carter", "calendar", "https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-1"),
        Source("finra_11_27", "fees", "https://www.finra.org/rules-guidance/notices/11-27"),
        Source("finra_12_06", "fees", "https://www.finra.org/rules-guidance/notices/12-06"),
        Source("finra_12_31", "fees", "https://www.finra.org/rules-guidance/notices/12-31"),
        Source("finra_2020_schedule", "fees", "https://www.finra.org/sites/default/files/2020-10/NOF%20IMM%20EFF%20FINRA-2020-032.pdf", ".pdf", review="official_document_manual_review; equity_TAF_table_page6"),
        Source("finra_2024_schedule", "fees", "https://www.finra.org/sites/default/files/2024-11/NOF-IMM-EFF-FINRA-2024-019.pdf", ".pdf", review="official_document_manual_review; equity_TAF_table_page6"),
        Source("finra_2026_waiver", "fees", "https://www.govinfo.gov/content/pkg/FR-2026-09-23/html/2026-19392.htm"),
    ])
    for _, _, identity, _ in SEC_RATES:
        prefix = "https://www.sec.gov/rules-regulations/fee-rate-advisories/" if identity in {"2024-2", "2025-2", "2026-2"} else SEC_PREFIX
        sources.append(Source("sec_" + identity, "fees", prefix + identity))
    return sources


def fee_periods(root: Path, receipts: dict, start: str, end: str) -> list[dict]:
    stop = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
    result = []
    for fee, changes in (("SEC_Section31", SEC_RATES), ("FINRA_equity_TAF", TAF_RATES)):
        for i, change in enumerate(changes):
            if fee == "SEC_Section31":
                effective, rate, value, evidence = change
                source_id, cap = "sec_" + value, None
            else:
                effective, rate, cap, source_id, evidence = change
            next_date = changes[i + 1][0] if i + 1 < len(changes) else stop
            left, right = max(effective, start), min(next_date, stop)
            if left >= right:
                continue
            receipt = receipts[source_id]
            checked = receipt["fetch_status"] == "success"
            if checked and fee == "SEC_Section31":
                text = source_text((root / receipt["file"]).read_bytes())
                checked = all(token in text for token in ("Section 31", evidence, f"${rate:.2f}"))
            inferred = "inferred" in evidence
            result.append({"fee": fee, "effective_date": effective, "start_inclusive": left,
                           "end_exclusive": right, "rate": rate if checked else None,
                           "unit": "USD_per_million_covered_sales" if fee == "SEC_Section31" else "USD_per_share_covered_sale",
                           "cap_per_trade_USD": cap if checked else None,
                           "source_id": source_id, "source_sha256": receipt.get("sha256"),
                           "source_observed_at": receipt.get("observed_at"),
                           "evidence": evidence, "verification": "inferred_continuity" if checked and inferred else "official_reference_reviewed" if checked else "unverified",
                           "effective_time_basis": "SEC_charge_date; broker_trade_date_mapping_unresolved" if fee == "SEC_Section31" else "transaction_date",
                           "broker_pass_through_verified": False, "historical_asof_verified": False})
    return result


def write_csv(path: Path, fields: tuple[str, ...], rows) -> int:
    count = 0
    if path.suffix == ".gz":
        stream = gzip.open(path, "xt", encoding="utf-8", newline="")
    else:
        stream = path.open("x", encoding="utf-8", newline="")
    with stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def supplement_data(data_root: Path, out: Path, repo: Path, end="2026-10-01", *,
                    external_root: Path = EXTERNAL_ROOT, source_cache: Path | None = None, progress=None) -> dict:
    panel = load_public_panel(data_root, end)
    source_manifest = read_json(data_root / "manifest.json")
    new_directory(out, kind="datasets", external_root=external_root)
    for category in ("normalized", "audit", "metadata", "assumptions", "provenance/run-code"):
        (out / category).mkdir(parents=True)
    sources = source_plan()
    write_json(out / "metadata/source-plan.json", GUARDS | {"sources": [asdict(source) for source in sources]})
    prior, cache_hash = {}, None
    if source_cache is not None:
        source_cache.resolve().relative_to(external_root.resolve() / "datasets/etf_alpha_p3")
        cache_manifest = read_json(source_cache / "manifest.json")
        if cache_manifest.get("research_only") is not True or cache_manifest.get("orders_authorized") is not False:
            raise ValueError("research-only source cache required")
        verify_files(source_cache, cache_manifest["files"])
        cache_hash = sha256(source_cache / "manifest.json")
        prior = {row["source_id"]: row for row in read_json(source_cache / "metadata/source-registry.json")["sources"]}
    receipts = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for receipt in executor.map(lambda source: fetch_source(source, out, cache=source_cache,
                                    prior=prior.get(source.source_id), cache_hash=cache_hash), sources):
            receipts[receipt["source_id"]] = receipt
            if progress:
                progress({"source_id": receipt["source_id"], "fetch_status": receipt["fetch_status"],
                          "bytes": receipt.get("bytes", 0), "error_class": receipt.get("error_class")})
    all_events = []
    for source in sources:
        receipt = receipts[source.source_id]
        if receipt["fetch_status"] != "success" or source.parser == "reference":
            continue
        try:
            raw = (out / receipt["file"]).read_bytes()
            if source.parser == "gld_policy":
                if "GLD does not generate any income" not in source_text(raw):
                    raise ValueError("GLD issuer non-income policy absent")
                rows = []
            elif source.parser == "ssga":
                rows = parse_ssga(raw, start=panel.dates[0], end=panel.dates[-1])
            elif source.parser == "ishares":
                rows = parse_ishares(raw, source.symbol)
            else:
                rows = parse_invesco(raw, source.symbol)
            for row in rows:
                row.update({"source_id": source.source_id, "source_sha256": receipt["sha256"],
                            "source_observed_at": receipt["observed_at"], "availability_class": "retrospective_snapshot"})
            receipt.update(normalization_status="parsed", parsed_rows=len(rows),
                           parsed_scope="declared_research_window" if source.parser == "ssga" else "full_issuer_history")
            all_events.extend(rows)
        except (ValueError, KeyError, TypeError, IndexError, ETParseError) as error:
            receipt.update(normalization_status="quarantined", error_class=type(error).__name__)
    events = unique_events([row for row in all_events if panel.dates[0] <= row["ex_date"] <= panel.dates[-1]])
    legacy, series = {}, {}
    symbols = (*panel.symbols, "BIL")
    for symbol in symbols:
        item = _series(data_root, symbol, source_manifest["files"][symbol], panel.dates[0], panel.dates[-1])
        series[symbol] = item
        for date, cash in zip(item["dates"], item["dividends"]):
            if cash > 0:
                legacy[(symbol, date)] = float(cash)
    def prices():
        for symbol, item in series.items():
            for i, date in enumerate(item["dates"]):
                yield {"symbol": symbol, "date": date,
                       **{key: float(item[key][i]) for key in ("open", "high", "low", "close", "volume", "splits")}}
    price_count = write_csv(out / "normalized/ohlcv.csv.gz", (
        "symbol", "date", "open", "high", "low", "close", "volume", "splits"), prices())
    reconciliation, detail = reconcile_events(events, legacy)
    reconciliation["GLD"] = {"issuer_rows": 0, "issuer_positive_rows": 0, "legacy_rows": 0,
        "statuses": {}, "classification": "non_income_issuer_policy; no_invented_dividend_records"}
    statuses = {(row["symbol"], row["ex_date"]): row["status"] for row in detail}
    for row in events:
        row.update(reconciliation_status=statuses[(row["symbol"], row["ex_date"])],
                   event_class="cash_distribution" if row["cash_per_share"] > 0 else "zero_cash_calendar_marker",
                   training_eligible=False)
    with (out / "normalized/distributions.jsonl.gz").open("xb") as byte_stream:
        with gzip.GzipFile(fileobj=byte_stream, mode="wb", mtime=0) as zipped:
            for row in events:
                zipped.write((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode())
    event_count = write_csv(out / "normalized/distributions.csv", (
        "symbol", "ex_date", "record_date", "pay_date", "cash_per_share", "currency", "share_basis",
        "source_id", "source_sha256", "source_observed_at", "availability_class", "historical_asof_verified",
        "reconciliation_status", "event_class", "training_eligible"), events)
    write_csv(out / "audit/distribution-reconciliation.csv", (
        "symbol", "ex_date", "issuer_cash_per_share", "legacy_nominal_cash_per_share", "status"), detail)
    calendar = equity_calendar(panel.dates[0], panel.dates[-1])
    write_csv(out / "normalized/exchange-calendar.csv", (
        "date", "is_session", "closure_reason", "special_source_id", "method", "intraday_hours_verified"), calendar)
    calendar_audit = compare_sessions(calendar, panel.dates)
    calendar_sources = [source.source_id for source in sources if source.category == "calendar"]
    calendar_audit.update({"source_ids": calendar_sources, "independent_of_price_sessions": True,
                           "intraday_and_settlement_hours": "not_verified",
                           "source_documents_available": all(receipts[key]["fetch_status"] == "success" for key in calendar_sources)})
    if not calendar_audit["source_documents_available"]:
        calendar_audit["status"] = "insufficient_source_evidence"
    fees = fee_periods(out, receipts, panel.dates[0], panel.dates[-1])
    write_csv(out / "normalized/regulatory-fee-periods.csv", (
        "fee", "effective_date", "start_inclusive", "end_exclusive", "rate", "unit", "cap_per_trade_USD",
        "source_id", "source_sha256", "source_observed_at", "evidence", "verification", "effective_time_basis",
        "broker_pass_through_verified", "historical_asof_verified"), fees)
    write_json(out / "assumptions/frozen-p2-costs.json", cost_contract() | {
        "classification": "research_assumption; not_observed_historical_cost",
        "applied_to_models_or_simulation": False})
    write_json(out / "metadata/input-reference.json", GUARDS | {
        "data_root": str(data_root), "manifest_sha256": sha256(data_root / "manifest.json"),
        "source_observed_at": source_manifest["observed_at"], "files": panel.audit["files"],
        "input_originals_modified": False, "price_basis": panel.audit["price_basis"],
        "volume_basis": "restored using declared split factors; independent volume convention not verified"})
    dictionary = GUARDS | {"schema": "etf-alpha-public-supplement-v1", "dataset_id": out.name,
        "date_range": [panel.dates[0], panel.dates[-1]], "symbols": list(symbols),
        "classes": {
            "raw/distributions": "unmodified official issuer snapshots; historical_asof_verified=false",
            "raw/calendar": "exchange rule/holiday/exception evidence; derived dates independent of price input",
            "raw/fees": "regulatory fee references; SEC charge date and FINRA transaction date distinguished",
            "normalized": "typed retrospective research tables; not a training qualification certificate",
            "assumptions": "frozen P2 commission/spread/impact estimates, kept separate from official rates",
            "audit": "coverage, reconciliation and unresolved requirements",
            "metadata": "source registry, field contracts and references",
            "provenance": "the exact public code used for acquisition and normalization"},
        "price_contract": "nominal reconstructed OHLC, split-restored volume; no adjusted-close feature",
        "event_contract": "cash totals include income and capital gains; zero-cash rows retained and labelled",
        "out_of_window_contract": "full raw sources retained; normalization qualifies only the declared research window",
        "source_quality_note": "SSGA workbook contains a BIL 2008-03-03 row with February record/payment dates; outside this research window, retained raw and not corrected",
        "payment_contract": "entitlement on ex-date is a receivable; pay-date transfer cannot increase NAV twice",
        "pay_dates_after_cutoff": "retained as reported future settlement, not evidence of completed payment",
        "fee_contract": "periods are left-inclusive/right-exclusive; null rate means missing evidence, never zero",
        "availability_contract": "source_observed_at is actual acquisition; historic announcement/available_at unknown",
        "GLD": "issuer non-income policy and zero legacy events; no invented dividend records",
        "training_authorized": False}
    write_json(out / "metadata/data-dictionary.json", dictionary)
    write_json(out / "metadata/source-registry.json", GUARDS | {"sources": list(receipts.values())})
    blockers = [
        "historical_price_and_event_asof_vintages_unavailable",
        "issuer_vs_vendor_amount_or_event_conflicts_require_resolution",
        "pay_date_receivable_accounting_not_yet_integrated_into_new_M1_run",
        "historical_bid_ask_and_impact_observations_unavailable",
        "broker_commission_pass_through_and_SEC_charge_date_mapping_unverified",
        "early_TAF_rate_continuity_inferred_not_independently_verified",
    ]
    if calendar_audit["status"] != "pass":
        blockers.append("exchange_calendar_or_source_evidence_incomplete")
    if any(receipt["fetch_status"] != "success" or receipt["normalization_status"] == "quarantined"
           for receipt in receipts.values()):
        blockers.append("public_source_fetch_or_parser_incomplete")
    incomplete_sources = any(r["fetch_status"] != "success" or r["normalization_status"] == "quarantined" for r in receipts.values())
    report = GUARDS | {"dataset_id": out.name, "dataset_root": str(out),
        "status": "public_sources_partial" if incomplete_sources else "public_sources_supplemented",
        "start": panel.dates[0], "end": panel.dates[-1], "sessions": len(panel.dates),
        "price_rows": price_count, "issuer_event_rows": event_count,
        "issuer_positive_events": sum(row["cash_per_share"] > 0 for row in events),
        "issuer_zero_cash_rows": sum(row["cash_per_share"] == 0 for row in events),
        "material_event_conflicts": sum(row["status"] in {"legacy_only", "issuer_only_positive", "amount_mismatch_requires_review"} for row in detail),
        "pay_dates_after_cutoff": sum(row["pay_date"] > panel.dates[-1] for row in events),
        "all_pay_dates_present": bool(events) and all(bool(row["pay_date"]) for row in events),
        "source_count": len(sources), "sources_fetched": sum(r["fetch_status"] == "success" for r in receipts.values()),
        "quarantined_sources": [key for key, r in receipts.items() if r["normalization_status"] == "quarantined"],
        "calendar": calendar_audit, "distribution_reconciliation": reconciliation,
        "regulatory_fee_periods": len(fees), "fee_reference_unverified_periods": sum(row["verification"] == "unverified" for row in fees),
        "fee_inferred_periods": [row for row in fees if row["verification"] == "inferred_continuity"],
        "D_gate": {"status": "insufficient", "blockers": blockers, "M2_authorized_by_D_gate": False},
        "prediction_training_status": "not_run", "historical_asof_verified": False,
        "original_input_files_reverified": len(verify_files(data_root, panel.audit["files"]))}
    write_json(out / "audit/data-audit.json", report)
    write_json(out / "audit/outstanding-data.json", GUARDS | {"required": blockers,
        "asof_requirement": "dated vendor revision/availability archive or genuinely new forward vintages; today's history is not PIT",
        "bid_ask_requirement": "licensed historical quote source or owner-supplied non-secret research export; estimates stay assumptions",
        "correction_requirement": "resolve issuer/vendor differences, freeze new receivable accounting and rerun data gate before Alpha training"})
    code_paths = ["src/qount/research/etf_alpha/" + name for name in
                  ("artifacts.py", "data.py", "data_sources.py", "data_supplement.py", "contracts.py")]
    code_paths += ["scripts/research/etf_alpha_supplement.py", "tests/test_etf_alpha_data_sources.py"]
    code_hashes = {}
    for relative in code_paths:
        original = repo / relative
        destination = out / "provenance/run-code" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        code_hashes[relative] = sha256(destination)
    write_json(out / "provenance/code-manifest.json", GUARDS | {"files": code_hashes})
    finish_manifest(out, schema="etf-alpha-public-supplement-v1", dataset_id=out.name,
                    storage_class="immutable_research_dataset", D_gate_status=report["D_gate"]["status"],
                    historical_asof_verified=False, training_authorized=False,
                    input_manifest_sha256=sha256(data_root / "manifest.json"))
    return report
