"""CLI: python3 -m riskdash report positions.csv --out outputs/ [--market market.json]"""

import argparse
import sys

from .portfolio import PositionValidationError
from .report import write_report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="riskdash", description="Options position risk dashboard (synthetic demo).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="build HTML dashboard + JSON summary for a positions CSV")
    rp.add_argument("positions", help="positions CSV")
    rp.add_argument("--out", default="outputs", help="output directory (default: outputs)")
    rp.add_argument("--market", default=None, help="market snapshot JSON (default: market.json next to the CSV)")
    rp.add_argument("--delta-threshold-lots", type=float, default=0.5,
                    help="flag when |net delta| exceeds this many lots-equivalent (default 0.5)")
    rp.add_argument("--title", default=None, help="dashboard title")
    args = ap.parse_args(argv)
    try:
        html_path, json_path, s = write_report(args.positions, args.out, args.market,
                                               args.delta_threshold_lots, args.title)
    except PositionValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print("wrote %s" % html_path)
    print("wrote %s" % json_path)
    for w in s["warnings"]:
        print("[%s] %s: %s" % (w["level"].upper(), w["topic"], w["text"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
