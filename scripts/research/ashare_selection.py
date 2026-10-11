"""Run immutable A-share source/window qualification on WSL and mounted E."""
import argparse
import json
from pathlib import Path

from qount.research.ashare_selection import qualify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--calendar-sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = qualify(contract_path=args.contract, calendar_path=args.calendar_sources, out=args.out)
    print(json.dumps({key: result[key] for key in ('files_profiled', 'rows_streamed',
          'study_session_count', 'window_available_median', 'data_gates', 'returns_produced',
          'artifact_root', 'manifest_sha256')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
