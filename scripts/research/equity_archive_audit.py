"""Audit an immutable user equity ZIP on WSL/E without return calculations."""
import argparse
import json
from pathlib import Path

from qount.research_data.equity_archive import audit_archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_archive(archive_path=args.archive, expected_sha256=args.sha256, out=args.out)
    print(json.dumps({k: result[k] for k in ('csv_files', 'rows', 'first_date', 'last_date',
          'complete_adjustment_rows', 'files_with_structural_issues', 'manifest_sha256', 'artifact_root')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
