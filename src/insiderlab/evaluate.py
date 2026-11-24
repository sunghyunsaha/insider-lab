"""Evaluate every leg and specification, test the pre-registered hypotheses, and run the
overfit-lab diagnostics (deflated Sharpe ratio, PBO via CSCV, Holm and BH).
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd
import statsmodels.api as sm
from overfitlab.diagnostics.multiple import benjamini_hochberg, holm, survivors
from overfitlab.diagnostics.pbo import cscv
from overfitlab.diagnostics.sharpe import deflated_sharpe_ratio, return_moments
from overfitlab.diagnostics.trials import effective_trials
from scipy.stats import norm

from .backtest import Market, leg_masks, leg_returns, one_way_cost
from .hypotheses import CONFIRMATORY, HYPOTHESES, PRIMARY_SPEC

DAYS = 252


def hac_test(x: np.ndarray, lags: int) -> dict:
    """Mean of ``x`` with a Newey-West t-statistic and one-sided p-value (H1: mean > 0)."""
    x = np.asarray(x, dtype=float)
    if len(x) < 30 or np.nanstd(x) == 0:
        return {"mean": float(np.nanmean(x)) if len(x) else 0.0, "t": 0.0, "p": 1.0}
    res = sm.OLS(x, np.ones_like(x)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    t = float(res.tvalues[0])
    return {"mean": float(res.params[0]), "t": t, "p": float(norm.sf(t))}


def capm_alpha(x: np.ndarray, bench: np.ndarray, lags: int) -> dict:
    """Intercept of x on the benchmark return (Newey-West): excess not explained by beta."""
    x, b = np.asarray(x, dtype=float), np.asarray(bench, dtype=float)
    if len(x) < 30 or np.std(x) == 0:
        return {"alpha": 0.0, "t": 0.0, "beta": 0.0}
    res = sm.OLS(x, sm.add_constant(b)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"alpha": float(res.params[0]), "t": float(res.tvalues[0]), "beta": float(res.params[1])}


def spec_name(leg: str, lag: int, horizon: int) -> str:
    return f"{leg}|lag{lag}|h{horizon}"


def run_grid(
    ev: pd.DataFrame,
    mkt: Market,
    cfg: dict,
    t_end: int,
    cost_mult: float = 1.0,
    delist: float | None = None,
    specs=None,
) -> dict[str, dict]:
    delist = cfg["delisting"]["primary_return"] if delist is None else delist
    masks = leg_masks(ev, cfg)
    cost = one_way_cost(ev["adv_usd"].to_numpy(), cfg, cost_mult)
    specs = specs or list(product(cfg["signal"]["lags"], cfg["signal"]["horizons"]))
    out = {}
    for leg, m in masks.items():
        sub = ev[m]
        for lag, h in specs:
            r = leg_returns(sub, mkt, lag, h, cost[m], delist, t_end)
            r["n_events"] = int(m.sum())
            out[spec_name(leg, lag, h)] = r
    return out


def column_stats(grid: dict[str, dict], start: int, lags: int) -> pd.DataFrame:
    rows = []
    for name, r in grid.items():
        x = r["excess"][start:]
        active = r["count"][start:] > 0
        test = hac_test(x, lags)
        leg, lag, h = name.split("|")
        rows.append(
            {
                "column": name,
                "leg": leg,
                "lag": int(lag[3:]),
                "horizon": int(h[1:]),
                "n_events": r["n_events"],
                "n_holdings": r["n_holdings"],
                "active_share": float(active.mean()),
                "ann_excess": float(np.mean(x) * DAYS),
                "ann_tracking_error": float(np.std(x, ddof=1) * np.sqrt(DAYS)),
                "info_ratio": float(np.mean(x) / np.std(x, ddof=1) * np.sqrt(DAYS))
                if np.std(x) > 0
                else 0.0,
                "t_hac": test["t"],
                "p_one_sided": test["p"],
                "mean_positions": float(r["count"][start:][active].mean()) if active.any() else 0.0,
            }
        )
    return pd.DataFrame(rows)


def matrix_diagnostics(grid: dict[str, dict], start: int, n_blocks: int) -> dict:
    names = [n for n in grid if np.std(grid[n]["excess"][start:]) > 0]
    x = np.column_stack([grid[n]["excess"][start:] for n in names])
    mom = return_moments(x)
    sr = mom["sharpe"]
    best = int(np.argmax(sr))
    n_obs = x.shape[0]
    dsr, sr0 = deflated_sharpe_ratio(
        float(sr[best]),
        n_obs,
        float(mom["skew"][best]),
        float(mom["kurt"][best]),
        float(len(names)),
        float(np.std(sr, ddof=1)),
    )
    eff = effective_trials(x, methods=("avg_corr", "eigen"))
    dsr_eff, sr0_eff = deflated_sharpe_ratio(
        float(sr[best]),
        n_obs,
        float(mom["skew"][best]),
        float(mom["kurt"][best]),
        float(max(eff["eigen"], 1.0)),
        float(np.std(sr, ddof=1)),
    )
    pbo = cscv(x, n_blocks=n_blocks)
    p = np.array([hac_test(x[:, j], 10)["p"] for j in range(x.shape[1])])
    return {
        "n_trials": len(names),
        "n_obs": n_obs,
        "best_column": names[best],
        "best_info_ratio_annual": float(sr[best] * np.sqrt(DAYS)),
        "expected_max_info_ratio_annual": float(sr0 * np.sqrt(DAYS)),
        "dsr": dsr,
        "effective_trials_eigen": float(eff["eigen"]),
        "effective_trials_avg_corr": float(eff["avg_corr"]),
        "dsr_effective_trials": dsr_eff,
        "pbo": pbo.pbo,
        "pbo_prob_oos_loss": pbo.prob_oos_loss,
        "pbo_blocks": n_blocks,
        "survivors_5pct": survivors(p, 0.05),
    }


def hypothesis_tests(
    grid: dict[str, dict],
    start: int,
    lags: int,
    spec: dict | None = None,
    bench: np.ndarray | None = None,
) -> list[dict]:
    spec = spec or PRIMARY_SPEC
    out = []
    for h in HYPOTHESES:
        cols = [spec_name(leg, spec["lag"], spec["horizon"]) for leg in h["legs"]]
        x = grid[cols[0]]["excess"][start:]
        if h["kind"] == "diff":
            x = x - grid[cols[1]]["excess"][start:]
        t = hac_test(x, lags)
        row = {
            "id": h["id"],
            "kind": h["kind"],
            "text": h["text"],
            "ann_effect": t["mean"] * DAYS,
            "t_hac": t["t"],
            "p_one_sided": t["p"],
            "n_events": [grid[c]["n_events"] for c in cols],
        }
        if bench is not None:
            a = capm_alpha(x, bench[start : start + len(x)], lags)
            row.update(
                {
                    "ann_alpha_capm": a["alpha"] * DAYS,
                    "t_alpha_capm": a["t"],
                    "beta_to_spy": a["beta"],
                }
            )
        out.append(row)
    conf = [r for r in out if r["id"] in CONFIRMATORY]
    p = np.array([r["p_one_sided"] for r in conf])
    for r, ph, pb in zip(conf, holm(p), benjamini_hochberg(p), strict=True):
        r["p_holm"], r["p_bh"] = float(ph), float(pb)
        r["supported"] = bool(ph < 0.05 and r["ann_effect"] > 0)
    for r in out:
        if r["kind"] == "control":
            r["supported"] = bool(r["p_one_sided"] >= 0.05)  # control passes if not positive
    return out


def subperiod_effects(
    grid: dict[str, dict], dates: pd.DatetimeIndex, periods, lags: int
) -> list[dict]:
    rows = []
    for a, b in periods:
        lo = dates.searchsorted(pd.Timestamp(a))
        hi = dates.searchsorted(pd.Timestamp(b), side="right")
        for r in hypothesis_tests(
            {k: {**v, "excess": v["excess"][:hi]} for k, v in grid.items()}, lo, lags
        ):
            rows.append(
                {
                    "period": f"{a[:4]}-{b[:4]}",
                    "id": r["id"],
                    "ann_effect": r["ann_effect"],
                    "t_hac": r["t_hac"],
                }
            )
    return rows


def krw_view(
    excess: np.ndarray, bench: np.ndarray, dates: pd.DatetimeIndex, fx: pd.Series, start: int
) -> dict:
    """Annualised KRW returns of the benchmark and of benchmark + excess (the signal sleeve)."""
    fxa = fx.reindex(dates).ffill().bfill().to_numpy()
    b = np.cumprod(1 + bench[start:])
    s = np.cumprod(1 + bench[start:] + excess[start:])
    years = len(b) / DAYS
    conv = fxa[start + len(b) - 1] / fxa[start]
    return {
        "years": years,
        "benchmark_krw_cagr": float((b[-1] * conv) ** (1 / years) - 1),
        "signal_krw_cagr": float((s[-1] * conv) ** (1 / years) - 1),
        "usdkrw_start": float(fxa[start]),
        "usdkrw_end": float(fxa[start + len(b) - 1]),
        "signal_curve": s.tolist(),
        "benchmark_curve": b.tolist(),
    }
