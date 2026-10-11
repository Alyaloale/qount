"""Run one frozen, source-qualified conditional A-share information study."""
import argparse
import json
from pathlib import Path

from qount.research.ashare_information_run import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract', 'qualification-root', 'source-root', 'calendar', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(contract_path=args.contract, qualification_root=args.qualification_root,
                 source_root=args.source_root, calendar_path=args.calendar, out=args.out)
    print(json.dumps({'status': result['status'], 'information_gate': result['information_gate']['status'],
                      'orders_authorized': result['orders_authorized'], 'artifact_root': str(args.out)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
