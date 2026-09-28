"""Read and build research-only CTA-R public ETF input seeds."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import zipfile
from typing import Mapping, Sequence


CTA_R_ETF_SYMBOLS = (
    "510300", "510500", "159915", "510050",
    "518880", "511010", "513100", "513500",
)
SEED_SCHEMA = "cta_r_akshare_seed_v1"
MAX_SEED_BYTES = 32 * 1024 * 1024


class CtaRSeedError(ValueError):
    pass


def inspect_seed_zip(
    path: Path,
    *,
    observed_at: dt.datetime,
    max_age_calendar_days: int = 7,
) -> dict[str, object]:
    """Validate the bounded qfq ZIP and report each ETF series without extracting it."""
    if observed_at.tzinfo is None or max_age_calendar_days < 1:
        raise CtaRSeedError("cta_r_seed_observation_invalid")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise CtaRSeedError("cta_r_seed_zip_unreadable") from error

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)

    with archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_SEED_BYTES:
            raise CtaRSeedError("cta_r_seed_size_limit")
        if len({info.filename for info in infos}) != len(infos):
            raise CtaRSeedError("cta_r_seed_duplicate_members")
        manifest_name = "metadata/manifest.json"
        if manifest_name not in {info.filename for info in infos}:
            raise CtaRSeedError("cta_r_seed_manifest_missing")
        try:
            manifest = json.loads(archive.read(manifest_name).decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
            raise CtaRSeedError("cta_r_seed_manifest_invalid") from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != SEED_SCHEMA
            or manifest.get("source") != "akshare"
            or manifest.get("adjustment") != "qfq"
            or tuple(manifest.get("symbols", ())) != CTA_R_ETF_SYMBOLS
        ):
            raise CtaRSeedError("cta_r_seed_contract_mismatch")

        observations: dict[str, dict[str, object]] = {}
        stale_symbols: list[str] = []
        errors: list[str] = []
        latest_cutoff = observed_at.astimezone(dt.UTC).date() - dt.timedelta(
            days=max_age_calendar_days
        )
        for symbol in CTA_R_ETF_SYMBOLS:
            member = f"etf_data/daily/{symbol}.csv"
            try:
                raw = archive.read(member)
            except KeyError:
                errors.append(f"{symbol}:missing")
                continue
            if len(raw) > MAX_SEED_BYTES:
                raise CtaRSeedError("cta_r_seed_member_size_limit")
            points: dict[dt.date, float] = {}
            try:
                reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
                if not {"trade_date", "close"}.issubset(reader.fieldnames or ()):
                    raise ValueError("columns")
                for row in reader:
                    text_date = (row.get("trade_date") or "").strip()
                    date_value = (
                        dt.datetime.strptime(text_date, "%Y%m%d").date()
                        if len(text_date) == 8 and text_date.isdigit()
                        else dt.date.fromisoformat(text_date[:10])
                    )
                    close = float(row["close"])
                    if not math.isfinite(close) or close <= 0:
                        continue
                    points[date_value] = close
            except (UnicodeDecodeError, csv.Error, KeyError, TypeError, ValueError):
                errors.append(f"{symbol}:malformed")
                continue
            if not points:
                errors.append(f"{symbol}:empty")
                continue
            latest = max(points)
            if latest < latest_cutoff:
                stale_symbols.append(symbol)
            observations[symbol] = {
                "latest_date": latest.isoformat(),
                "row_count": len(points),
            }

    status = "valid" if len(observations) == len(CTA_R_ETF_SYMBOLS) and not stale_symbols else "insufficient"
    return {
        "status": status,
        "reason_codes": errors + (["series_stale"] if stale_symbols else []),
        "stale_symbols": stale_symbols,
        "observations": observations,
        "seed_sha256": digest.hexdigest(),
        "adjustment": "qfq",
        "max_age_calendar_days": max_age_calendar_days,
        "strategy_results_evaluated": False,
    }


def write_seed_zip(
    output_path: Path,
    series_by_symbol: Mapping[str, Sequence[tuple[str, float]]],
    *,
    start_date: str,
    end_date: str,
) -> Path:
    """Write an exclusive, self-describing seed archive from adjusted daily closes."""
    if set(series_by_symbol) != set(CTA_R_ETF_SYMBOLS):
        raise CtaRSeedError("cta_r_seed_symbols_invalid")
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    if start > end:
        raise CtaRSeedError("cta_r_seed_date_range_invalid")
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": SEED_SCHEMA,
        "source": "akshare",
        "adjustment": "qfq",
        "symbols": list(CTA_R_ETF_SYMBOLS),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "research_only": True,
        "orders_authorized": False,
    }
    created = False
    try:
        with output_path.open("xb") as output, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            created = True
            archive.writestr(
                "metadata/manifest.json",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            )
            for symbol in CTA_R_ETF_SYMBOLS:
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                writer.writerow(("trade_date", "close"))
                valid_rows = 0
                for raw_date, raw_close in sorted(series_by_symbol[symbol]):
                    date_value = dt.date.fromisoformat(str(raw_date)[:10])
                    close = float(raw_close)
                    if start <= date_value <= end and math.isfinite(close) and close > 0:
                        writer.writerow((date_value.strftime("%Y%m%d"), format(close, ".12g")))
                        valid_rows += 1
                if not valid_rows:
                    raise CtaRSeedError(f"cta_r_seed_series_empty:{symbol}")
                archive.writestr(f"etf_data/daily/{symbol}.csv", buffer.getvalue())
        os.chmod(output_path, 0o600)
    except BaseException:
        if created:
            output_path.unlink(missing_ok=True)
        raise
    return output_path
