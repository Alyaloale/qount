"""Query Fuyao/THS from Mac using ~/.config/qount/fuyao.env; never accept keys on CLI."""
import argparse
import json
from pathlib import Path

from qount.research_data.fuyao import CAPABILITIES, FuyaoClient, FuyaoError, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    query = sub.add_parser('query', help='One read-only query; dates may use YYYY-MM-DD')
    query.add_argument('capability', choices=sorted(CAPABILITIES))
    query.add_argument('--param', action='append', default=[], metavar='NAME=VALUE')
    query.add_argument('--output', type=Path, help='New non-secret JSON output; refuses overwriting')
    check = sub.add_parser('probe', help='Ten small serial queries, no automatic retries')
    check.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('output already exists; use a new path')
    params = {}
    for argument in getattr(args, 'param', []):
        name, separator, value = argument.partition('=')
        if not separator or name in params:
            parser.error('each parameter must be unique NAME=VALUE')
        params[name] = value
    try:
        client = FuyaoClient()
        record = probe(client) if args.command == 'probe' else client.query(args.capability, **params)
        rendered = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(rendered)
        if args.command == 'probe':
            print(rendered, end='')
            return 0 if record['ok'] else 1
        print(json.dumps({'source': record['source'], 'endpoint': record['endpoint'],
            'rows': len(record['response']['data']['item']), 'semantics': record['semantics'],
            'output': str(args.output) if args.output else None}, ensure_ascii=False))
        if not args.output:
            print(rendered, end='')
        return 0
    except (FuyaoError, ValueError, OSError) as exc:
        # Do not expose traceback, provider response text, headers or credential contents.
        safe = str(exc) if isinstance(exc, FuyaoError) or str(exc).startswith('credential_') else 'fuyao_local_input_or_output_error'
        print(json.dumps({'ok': False, 'error': safe}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
