#!/usr/bin/env python3
"""CLI entry: Monday 10:00 grade job (and Poisson self-tune when in Poisson mode)."""
import argparse
import sys

import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    res = pipeline.run_grade(data_dir=args.data_dir)
    print(f"Graded: {res['graded']} predictions, {res['hits']} correct"
          + (f" ({res['acc']:.1%})" if res["acc"] is not None else ""))
    bt = res["backtest"]
    if bt is None:
        print("Backtest/refit: skipped (gap mode — nothing to tune)")
    else:
        print(f"Backtest over real played rounds: {bt['n']} picks, {bt['hits']} correct"
              + (f" ({bt['acc']:.1%})" if bt["acc"] else "") +
              f" | top-{bt['top_n']}: {bt['top_hits']} hit" +
              (f" ({bt['top_acc']:.1%})" if bt["top_acc"] else ""))
        if res["refit"]:
            rp = res["refit"]
            print(f"Refit: new params w_form={rp['w_form']} shrink={rp['shrink']}")
        else:
            print("Refit: no change (not enough data yet)")
    if res["errors"]:
        print("Warnings:", "; ".join(res["errors"]))
    print("Dashboard:", res["dashboard"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
