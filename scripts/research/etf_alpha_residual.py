#!/usr/bin/env python3
"""Thin adapter for preparing and explicitly activating the R3 research engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from qount.research.etf_alpha.artifacts import GUARDS, read_json, utc_now, write_json
from qount.research.etf_alpha.residual_runtime import check_ready, launch, pack_delivery, prepare_engine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository",type=Path,default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command",required=True)
    for command in ("pack","prepare"):
        p = commands.add_parser(command)
        p.add_argument("--contract",type=Path,required=True)
        p.add_argument("--out",type=Path,required=True)
    p = commands.add_parser("check")
    p.add_argument("--ready",type=Path,required=True)
    p = commands.add_parser("status")
    p.add_argument("--path",type=Path,required=True)
    for command in ("launch","run"):
        p = commands.add_parser(command)
        p.add_argument("--ready",type=Path,required=True)
        p.add_argument("--authorization",type=Path)
        p.add_argument("--out",type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"launch","run"} and args.authorization is None:
            raise PermissionError("ready_waiting_owner: a later explicit training instruction is required")
        if args.command=="pack":
            result = pack_delivery(args.repository,args.contract,args.out)
        elif args.command=="prepare":
            result = prepare_engine(args.contract,args.out,args.repository)
        elif args.command=="check":
            result = check_ready(args.ready,args.repository)
        elif args.command=="status":
            name = "status.json" if (args.path/"status.json").exists() else "READY.json"
            result = read_json(args.path/name)
        elif args.command=="launch":
            result = launch(args.ready,args.authorization,args.out,args.repository)
        else:
            from qount.research.etf_alpha.residual_run import run_engine
            result = run_engine(args.ready,args.authorization,args.out,args.repository)
            code = 0 if result["status"] in {"complete","pilot_no_increment"} else 130 if result["status"]=="owner_or_signal_stopped" else 1
            write_json(Path(str(args.out)+".exit.json"),GUARDS|{"finished_at":utc_now(),"exit_code":code,
                "status":result["status"],"output_root":str(args.out),"automatic_restart_authorized":False})
            print(json.dumps({k:v for k,v in result.items() if k not in {"outer_test","inner_fits","selections"}},ensure_ascii=False,allow_nan=False))
            return code
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except (PermissionError,ValueError,RuntimeError,OSError) as error:
        print(f"{type(error).__name__}: {error}",file=sys.stderr)
        # A launched supervisor retains a preflight failure receipt, without creating a fit directory.
        reservation = Path(str(getattr(args,"out",""))+".launch.json")
        if args.command=="run" and args.authorization is not None and reservation.exists():
            destination = Path(str(args.out)+".exit.json")
            if not destination.exists():
                write_json(destination,GUARDS|{"finished_at":utc_now(),"exit_code":2,"status":"preflight_failed",
                    "error":f"{type(error).__name__}: {error}","automatic_restart_authorized":False})
        return 2


if __name__=="__main__":
    raise SystemExit(main())
