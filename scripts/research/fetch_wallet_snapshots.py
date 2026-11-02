#!/usr/bin/env python3
"""Extract a small fixed-address panel from bounded public daily snapshots.

Use HTTP column ranges for small local experiments, or read cached Parquet
on the existing E research disk. No account credentials or trading endpoints.
DuckDB reads local files; the range option additionally uses PyArrow.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request

import duckdb


REPO = "ProbioticFarmer/hyperliquid-augmented-copytrading"
COINS = ["BTC", "ETH", "HYPE", "ZEC"]


class RangeFile(io.RawIOBase):
    """Bounded HTTP random reads; require the server's exact byte range."""
    def __init__(self, url, size):
        self.url, self.size, self.position, self.bytes_read = url, size, 0, 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if not 0 <= self.position <= self.size:
            raise ValueError("range_seek_outside_file")
        return self.position

    def read(self, count=-1):
        begin = self.position
        count = self.size - begin if count < 0 else min(count, self.size - begin)
        if count == 0: return b""
        end = begin + count - 1
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={begin}-{end}"})
        with urllib.request.urlopen(request, timeout=25) as response:
            assert response.status == 206 and response.headers.get("Content-Range") == f"bytes {begin}-{end}/{self.size}", "incorrect_http_range"
            data = response.read(count)
        assert len(data) == count, "short_http_range"
        self.bytes_read += count
        assert self.bytes_read <= 25_000_000, "range_byte_budget"
        self.position += count
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addresses", type=Path, required=True)
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-total-mb", type=int, default=400)
    parser.add_argument("--ephemeral-raw", action="store_true", help="Extract one <=25MB local temporary file at a time; retain only the small panel")
    parser.add_argument("--range-columns", action="store_true", help="Read only user/market/size via HTTP ranges; requires pyarrow; retain no raw files")
    args = parser.parse_args()
    addresses = json.loads(args.addresses.read_text())
    assert len(addresses) == len(set(addresses))
    temporary = tempfile.TemporaryDirectory(prefix="qount-wallet-snapshots-") if args.ephemeral_raw else None
    local_cache = Path(temporary.name) if temporary else args.cache
    local_cache.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("set threads=1")
    connection.execute("create table wanted(address varchar)")
    connection.executemany("insert into wanted values (?)", [(a,) for a in addresses])
    panel = []; total = 0
    for date in args.dates:
        url = f"https://huggingface.co/api/datasets/{REPO}/tree/main/snapshots_perp/date={date}?limit=5"
        entries = json.load(urllib.request.urlopen(url, timeout=40))
        files = [f for f in entries if f["type"] == "file" and f["path"].endswith(".parquet")]
        assert len(files) == 1, "ambiguous_daily_snapshot"
        source = files[0]; total += source["size"]
        assert source["size"] <= 25_000_000 and total <= args.max_total_mb * 1_000_000, "snapshot_byte_budget"
        stamp = int(Path(source["path"]).stem.split("_")[-1])
        assert datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime("%Y-%m-%d") == date
        if args.range_columns:
            import pyarrow as pa
            import pyarrow.compute as pc
            import pyarrow.parquet as pq
            reader = RangeFile(f"https://huggingface.co/datasets/{REPO}/resolve/main/{source['path']}?download=true", source['size'])
            table = pq.ParquetFile(reader).read(columns=["user", "market", "size"], use_threads=False)
            table = table.filter(pc.and_(pc.is_in(table['user'], value_set=pa.array(addresses)),
                                         pc.is_in(table['market'], value_set=pa.array(COINS))))
            positions = {a: {c: 0. for c in COINS} for a in addresses}; seen = set()
            for row in table.to_pylist():
                key = (row['user'], row['market'])
                assert key not in seen, "duplicate_snapshot_position"
                seen.add(key); positions[key[0]][key[1]] = row['size']
            panel.append(dict(date=date, time_ms=stamp, source=source['path'], bytes=source['size'],
                              fetched_column_bytes=reader.bytes_read, positions=positions))
            print(date, "selected_nonzero_positions", len(seen), "column_bytes", reader.bytes_read, flush=True)
            continue
        target = local_cache / (date + ".parquet")
        # Existing probe files may seed the temporary cache.
        seed = args.cache / (date + ".parquet")
        if temporary and seed.exists():
            target.write_bytes(seed.read_bytes())
        if not target.exists():
            url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{source['path']}?download=true"
            fetched = subprocess.run(["curl", "--fail", "--silent", "--location", "--connect-timeout", "15",
                                      "--max-time", "90", "--max-filesize", "25000000", "--output", str(target), url],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if fetched.returncode:
                raise RuntimeError(f"bounded_snapshot_download_failed:{date}:curl{fetched.returncode}")
            data = target.read_bytes()
            assert len(data) == source["size"] and data[:4] == data[-4:] == b"PAR1", "invalid_snapshot_download"
        assert target.stat().st_size == source["size"], "cached_snapshot_size"
        rows = connection.execute('''select p."user", market, size from read_parquet(?) p
                                    join wanted w on p."user"=w.address
                                    where market in ('BTC','ETH','HYPE','ZEC')''', [str(target)]).fetchall()
        positions = {a: {c: 0. for c in COINS} for a in addresses}
        seen = set()
        for address, coin, size in rows:
            assert (address, coin) not in seen, "duplicate_snapshot_position"
            seen.add((address, coin)); positions[address][coin] = size
        panel.append(dict(date=date, time_ms=stamp, source=source["path"], bytes=source["size"],
                          sha256=hashlib.sha256(target.read_bytes()).hexdigest(), positions=positions))
        if temporary:
            target.unlink()
        print(date, "selected_nonzero_positions", len(rows), "bytes", source["size"], flush=True)
    payload = dict(research_only=True, orders_authorized=False, publisher=REPO,
                   addresses=addresses, coins=COINS, snapshots=panel,
                   limits=["Third-party full-position snapshots: absent address/market interpreted as zero, not independently certified",
                           "Snapshot timestamps are source times, not verified historical publication times",
                           "Daily net changes cannot recover intraday trades or their original decision times"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
