"""Read existing public CSV archives without a strategy dependency."""
import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def timestamp(date: str) -> int:
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())

def archive_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise ValueError("expected_single_csv")
        with archive.open(names[0]) as raw:
            return [row for row in csv.reader(io.TextIOWrapper(raw))
                    if row and row[0].isdigit()]
