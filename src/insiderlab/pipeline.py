"""End-to-end research run: events -> prices -> backtest -> diagnostics -> results JSON."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from . import events as E
from .backtest import Market, attach_price_features, build_market
from .evaluate import (
    column_stats,
    hypothesis_tests,
    krw_view,
    matrix_diagnostics,
    run_grid,
    spec_name,
    subperiod_effects,
)
from .hypotheses import PRIMARY_SPEC, REGISTERED


def prepare_events(tx: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    ev = E.purchase_events(tx, cfg["signal"])
    pop, steps = E.apply_population(ev, cfg)
    return pop, steps


def run(
    tx: pd.DataFrame,
    panel: dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    fx: pd.Series,
    cfg: dict,
    data_source: str,
    log=print,
) -> dict:
    s = cfg["sample"]
    log("building purchase events")
    pop, steps = prepare_events(tx, cfg)
    log(f"  {len(pop)} events after population filters")
    mkt: Market = build_market(panel, bench, s["history_start"], s.get("end"))
    ev, steps2 = attach_price_features(pop, mkt, cfg)
    steps.update({f"price_{k}": v for k, v in steps2.items()})
    dates = mkt.dates
    i0 = int(dates.searchsorted(pd.Timestamp(s["start"])))
    t_end = int(dates.searchsorted(pd.Timestamp(s["holdout_start"])))
    insample = ev[
        (ev["filing_date"] >= pd.Timestamp(s["start"]))
        & (ev["filing_date"] < pd.Timestamp(s["holdout_start"]))
    ].reset_index(drop=True)
    steps["in_sample_events"] = len(insample)
    log(f"  {len(insample)} in-sample events, {dates[i0].date()} to {dates[t_end - 1].date()}")

    ev_cfg = cfg["evaluation"]
    lags = ev_cfg["hac_lags"]
    log("running the grid (9 legs x lags x horizons)")
    grid = run_grid(insample, mkt, cfg, t_end)
    stats = column_stats(grid, i0, lags)
    diag = matrix_diagnostics(grid, i0, ev_cfg["cscv_blocks"])
    hyp = hypothesis_tests(grid, i0, lags, bench=mkt.bench[:t_end])

    log("robustness: other specifications, costs, delisting")
    robust = []
    for lag in cfg["signal"]["lags"]:
        for h in cfg["signal"]["horizons"]:
            spec = {"lag": lag, "horizon": h}
            for r in hypothesis_tests(grid, i0, lags, spec):
                robust.append({"spec": f"lag{lag}|h{h}|cost1x", **_short(r)})
    primary = [(PRIMARY_SPEC["lag"], PRIMARY_SPEC["horizon"])]
    for mult in cfg["costs"]["sensitivity_multipliers"]:
        if mult == 1.0:
            continue
        g = run_grid(insample, mkt, cfg, t_end, cost_mult=mult, specs=primary)
        for r in hypothesis_tests(g, i0, lags):
            robust.append({"spec": f"primary|cost{mult:g}x", **_short(r)})
    g = run_grid(
        insample, mkt, cfg, t_end, delist=cfg["delisting"]["sensitivity_return"], specs=primary
    )
    for r in hypothesis_tests(g, i0, lags):
        robust.append(
            {"spec": f"primary|delist{cfg['delisting']['sensitivity_return']:+.0%}", **_short(r)}
        )

    sub = subperiod_effects(grid, dates, ev_cfg["subperiods"], lags)
    h1 = grid[spec_name("all", PRIMARY_SPEC["lag"], PRIMARY_SPEC["horizon"])]
    krw = krw_view(h1["excess"][:t_end], mkt.bench[:t_end], dates[:t_end], fx, i0)

    curves = {
        name: np.cumsum(
            grid[spec_name(name, PRIMARY_SPEC["lag"], PRIMARY_SPEC["horizon"])]["excess"][i0:t_end]
        )
        for name in ["all", "opportunistic", "routine", "cluster", "single"]
    }
    return {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "registered": REGISTERED,
        "data_source": data_source,
        "sample": {
            "start": str(dates[i0].date()),
            "end": str(dates[t_end - 1].date()),
            "holdout_start": s["holdout_start"],
            "holdout": "locked",
        },
        "funnel": steps,
        "primary_spec": PRIMARY_SPEC,
        "hypotheses": hyp,
        "diagnostics": diag,
        "columns": stats.to_dict(orient="records"),
        "robustness": robust,
        "subperiods": sub,
        "krw": {k: v for k, v in krw.items() if not k.endswith("curve")},
        "curves": {
            "dates": [str(d.date()) for d in dates[i0:t_end]],
            **{k: v.tolist() for k, v in curves.items()},
        },
        "events_preview": insample.tail(5)[
            ["filing_date", "ticker", "owner_title", "value", "trader_class", "cluster_n"]
        ]
        .astype(str)
        .to_dict(orient="records"),
    }


def _short(r: dict) -> dict:
    return {
        "id": r["id"],
        "ann_effect": r["ann_effect"],
        "t_hac": r["t_hac"],
        "p_one_sided": r["p_one_sided"],
    }


def save(results: dict, out_dir) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    curves = results.pop("curves")
    (out_dir / "backtest.json").write_text(json.dumps(results, indent=2, default=_jsonable))
    pd.DataFrame(curves).to_csv(out_dir / "cumulative_excess.csv", index=False)
    results["curves"] = curves


def _jsonable(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return str(x)
