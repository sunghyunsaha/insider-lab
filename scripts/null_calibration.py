"""Size check of the whole pipeline: run it on synthetic worlds with NO planted effect and
count how often each pre-registered test rejects at 5%. A well-calibrated test rejects
about 5% of the time. Writes reports/results/null_calibration.json.

    python scripts/null_calibration.py --worlds 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from insiderlab import pipeline
from insiderlab.config import load_config
from insiderlab.synthetic import make_world


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=30)
    ap.add_argument("--first-seed", type=int, default=1000)
    args = ap.parse_args()
    cfg = load_config("configs/base.yaml")
    stats: dict[str, list[float]] = {}
    for seed in range(args.first_seed, args.first_seed + args.worlds):
        w = make_world(seed=seed, drift_daily=0.0, n_tickers=80, n_insiders=300)
        res = pipeline.run(
            w["tx"], w["panel"], w["bench"], w["fx"], cfg, "null", log=lambda *a: None
        )
        for h in res["hypotheses"]:
            stats.setdefault(h["id"], []).append(h["t_hac"])
        stats.setdefault("dsr", []).append(res["diagnostics"]["dsr"])
    out = {"worlds": args.worlds, "first_seed": args.first_seed, "tests": {}}
    for k, v in stats.items():
        a = np.array(v)
        if k == "dsr":
            out["dsr_share_at_least_0.95"] = float(np.mean(a >= 0.95))
            continue
        out["tests"][k] = {
            "mean_t": float(a.mean()),
            "sd_t": float(a.std(ddof=1)),
            "rejection_rate_5pct": float(np.mean(a > 1.6449)),
        }
    path = Path("reports/results/null_calibration.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
