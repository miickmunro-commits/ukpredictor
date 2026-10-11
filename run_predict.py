#!/usr/bin/env python3
"""CLI entry: Friday predict job."""
import argparse
import json
import sys

import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--json", action="store_true", help="emit machine-readable picks")
    args = ap.parse_args()
    res = pipeline.run_predict(data_dir=args.data_dir)
    if args.json:
        out = [{"rank": i + 1, "league": p["league"], "home": p["home"], "away": p["away"],
                "side": p["side"], "winner": p["winner"], "prob": round(p["prob"], 4)}
               for i, p in enumerate(res["picks"])]
        json.dump({"saturday": res["date"], "picks": out, "errors": res["errors"]}, sys.stdout, indent=2)
        return 0
    gap = res.get("mode", "gap") == "gap"
    print(f"Saturday 3pm fixtures: {res['date']}  (method: {'table gap' if gap else 'Poisson'})")
    print(f"Eligible matches: {res['n_eligible']} | new picks stored: {res['n_new']}")
    for i, p in enumerate(res["picks"], 1):
        print(f"  {i:2d}. {p['home']:22s} vs {p['away']:22s} -> {p['side']} ({p['winner']}) "
              + (f"#{p['rank_h']} v #{p['rank_a']}, gap {p['prob']:.0%}" if gap else f"@ {p['prob']:.1%}"))
    if res["errors"]:
        print("Warnings:", "; ".join(res["errors"]))
    print("Dashboard:", res["dashboard"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
