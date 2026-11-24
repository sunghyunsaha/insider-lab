"""Synthetic insider filings and prices with a known planted effect.

Used by the test-suite and ``insiderlab demo``: the pipeline must find the planted
effect (opportunistic and cluster purchases drift up) and must NOT find one for routine
purchases. No network needed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_world(
    seed: int = 0,
    n_tickers: int = 120,
    n_insiders: int = 500,
    start: str = "2006-01-02",
    end: str = "2025-12-31",
    drift_daily: float = 0.0004,
    beta_spread: float = 0.3,
) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    t_len = len(dates)
    tickers = [f"T{i:03d}" for i in range(n_tickers)]
    mkt = rng.normal(0.0003, 0.011, t_len)
    beta = rng.uniform(1 - beta_spread, 1 + beta_spread, n_tickers)
    idio = rng.normal(0.0, 0.02, (t_len, n_tickers))
    rets = mkt[:, None] * beta[None, :] + idio
    life_end = np.full(n_tickers, t_len - 1)
    dead = rng.choice(n_tickers, n_tickers // 10, replace=False)
    life_end[dead] = rng.integers(t_len // 3, t_len - 300, len(dead))

    rows = []
    routine = rng.random(n_insiders) < 0.3
    # Routine insiders get their own issuers so their windows never overlap planted drift.
    split_k = int(n_tickers * 0.35)
    insider_ticker = np.where(
        routine, rng.integers(0, split_k, n_insiders), rng.integers(split_k, n_tickers, n_insiders)
    )
    month = rng.integers(1, 13, n_insiders)
    for i in range(n_insiders):
        k = insider_ticker[i]
        if routine[i]:  # buys every year in the same month
            for y in range(dates[0].year, dates[-1].year + 1):
                d = pd.Timestamp(y, month[i], 10)
                rows.append((i, k, d, "routine"))
        else:  # most years one purchase in a random month
            for y in range(dates[0].year, dates[-1].year + 1):
                if rng.random() < 0.8:
                    m = int(rng.integers(1, 13))
                    rows.append(
                        (i, k, pd.Timestamp(y, m, int(rng.integers(1, 28))), "opportunistic")
                    )
    # clusters: 3 insiders of one issuer buying within ten days
    for _ in range(60):
        k = rng.integers(split_k, n_tickers)
        d0 = dates[rng.integers(800, t_len - 200)]
        candidates = np.flatnonzero(insider_ticker == k)
        members = rng.choice(candidates, 3, replace=False) if len(candidates) >= 3 else []
        for j, i in enumerate(members):
            rows.append((int(i), k, d0 + pd.Timedelta(days=3 * j), "cluster"))

    ev = pd.DataFrame(rows, columns=["owner", "k", "trans_date", "kind"])
    ev = ev[(ev["trans_date"] >= dates[0]) & (ev["trans_date"] <= dates[-1])]
    ev["t_idx"] = dates.searchsorted(ev["trans_date"])
    ev = ev[ev["t_idx"] < life_end[ev["k"].to_numpy()] - 5]
    for k, ti, kind in zip(ev["k"], ev["t_idx"], ev["kind"], strict=True):
        if kind in ("opportunistic", "cluster"):
            rets[ti + 1 : ti + 127, k] += drift_daily * (2.0 if kind == "cluster" else 1.0)

    price = 30 * np.cumprod(1 + rets, axis=0)
    panel = {}
    for k, t in enumerate(tickers):
        idx = dates[: life_end[k] + 1]
        px = price[: life_end[k] + 1, k]
        panel[t] = pd.DataFrame(
            {
                "close": px,
                "adj_close": px,
                "volume": 2e6 / px * 30,
                "split": 1.0,
                "source": "synthetic",
            },
            index=idx,
        )
    spy = 100 * np.cumprod(1 + mkt)
    bench = pd.DataFrame({"close": spy, "adj_close": spy, "volume": 1e8, "split": 1.0}, index=dates)
    fx = pd.Series(1200 + np.cumsum(rng.normal(0, 3, t_len)), index=dates, name="DEXKOUS")

    ev["filing_date"] = ev["trans_date"] + pd.Timedelta(days=2)
    px_at = price[ev["t_idx"].to_numpy(), ev["k"].to_numpy()]
    n = len(ev)
    shares = rng.integers(1000, 20000, n).astype(float)
    tx = pd.DataFrame(
        {
            "accession": [f"0000-{i:07d}" for i in range(n)],
            "trans_sk": np.arange(n).astype(str),
            "filing_date": ev["filing_date"].to_numpy(),
            "trans_date": ev["trans_date"].to_numpy(),
            "form": "4",
            "issuer_cik": ev["k"].astype(str).to_numpy(),
            "issuer_name": [f"Company {k} Inc" for k in ev["k"]],
            "ticker": [tickers[k] for k in ev["k"]],
            "security_title": "Common Stock",
            "code": "P",
            "acq_disp": "A",
            "shares": shares,
            "price": px_at,
            "owned_after": shares * rng.uniform(1.5, 30, n),
            "direct": "D",
            "equity_swap": False,
            "plan_10b5_1": False,
            "owner_cik": ev["owner"].astype(str).to_numpy(),
            "owner_name": [f"Insider {o}" for o in ev["owner"]],
            "owner_title": "Director",
            "n_owners": 1,
            "is_officer": False,
            "is_director": True,
            "is_ten_pct": False,
        }
    )
    return {"tx": tx, "panel": panel, "bench": bench, "fx": fx, "kinds": ev["kind"].to_numpy()}
