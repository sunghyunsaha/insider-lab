"""Calendar-time portfolio backtest of insider-purchase events.

Each *leg* (a subset of events, e.g. cluster buys) becomes one daily return series:

1. An event filed on trading day ``f`` is entered at the close of day ``f + lag``.
2. The position is held for ``horizon`` trading days. A new event in a ticker that is
   already held extends the holding instead of opening a second position.
3. Each day the leg's return is the equal-weighted mean of its open positions' returns,
   net of a one-way cost charged on the first and last day of each holding.
4. Excess return = leg return minus benchmark return on days with open positions, and 0
   on days without (the money sits in the benchmark). This is the series a long-only
   investor who swaps part of an index holding for the signal would earn relative to
   staying in the index.

The excess series of all legs form the T x N matrix that overfit-lab diagnoses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .prices import unadjusted_close

SPLIT_FACTORS = (1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 1 / 3, 0.25, 0.2, 0.1, 1.5, 2 / 3)


@dataclass
class Market:
    dates: pd.DatetimeIndex
    tickers: list[str]
    returns: np.ndarray  # T x K daily simple returns from adjusted close, NaN when absent
    last_valid: np.ndarray  # K, index of the last day with a price
    first_valid: np.ndarray  # K
    dollar_volume: np.ndarray  # T x K, close x volume
    bench: np.ndarray  # T, benchmark daily simple return
    raw_close: dict[str, pd.Series]  # as-traded close per ticker, for the ticker check
    no_split_info: set[str]

    def col(self, ticker: str) -> int | None:
        """Column of ``ticker``, or None when it has no prices."""
        if not hasattr(self, "_col"):
            self._col = {t: i for i, t in enumerate(self.tickers)}
        return self._col.get(ticker)


def build_market(
    panel: dict[str, pd.DataFrame], bench: pd.DataFrame, start: str, end: str | None = None
) -> Market:
    b = bench["adj_close"].sort_index()
    b = b[b.index >= pd.Timestamp(start)]
    if end:
        b = b[b.index <= pd.Timestamp(end)]
    dates = pd.DatetimeIndex(b.index)
    tickers = sorted(panel)
    t_len, k_len = len(dates), len(tickers)
    rets = np.full((t_len, k_len), np.nan, dtype=np.float64)
    dvol = np.full((t_len, k_len), np.nan, dtype=np.float64)
    first = np.full(k_len, -1, dtype=int)
    last = np.full(k_len, -1, dtype=int)
    raw, no_split = {}, set()
    for k, t in enumerate(tickers):
        df = panel[t]
        px = df["adj_close"].reindex(dates)
        valid = np.flatnonzero(px.notna().to_numpy())
        if len(valid) < 2:
            continue
        lo, hi = valid[0], valid[-1]
        px = px.iloc[lo : hi + 1].ffill(limit=5)
        r = px.pct_change().to_numpy(copy=True)
        r[0] = np.nan
        rets[lo : hi + 1, k] = r
        dv = (df["close"] * df["volume"]).reindex(dates).to_numpy(copy=True)
        dvol[:, k] = dv
        first[k], last[k] = lo, hi
        raw[t] = unadjusted_close(df)
        src = df["source"].iloc[0] if "source" in df else ""
        if src == "stooq":
            no_split.add(t)
    bench_ret = b.pct_change().fillna(0.0).to_numpy()
    return Market(dates, tickers, rets, last, first, dvol, bench_ret, raw, no_split)


def price_matches(close: float, reported: float, tol: float, try_splits: bool) -> bool:
    if not (np.isfinite(close) and close > 0 and reported > 0):
        return False
    factors = SPLIT_FACTORS if try_splits else (1.0,)
    return any(abs(close * f / reported - 1.0) <= tol for f in factors)


def attach_price_features(ev: pd.DataFrame, mkt: Market, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Add calendar indices, ticker check, liquidity and prior drawdown. Drops unusable events."""
    u, s = cfg["universe"], cfg["signal"]
    dates = mkt.dates
    steps: dict[str, int] = {"population": len(ev)}
    ev = ev[(ev["filing_date"] >= dates[0]) & (ev["filing_date"] <= dates[-1])].copy()
    steps["inside_price_calendar"] = len(ev)
    ev["k"] = [mkt.col(t) for t in ev["ticker"]]
    ev = ev[ev["k"].notna()].copy()
    ev["k"] = ev["k"].astype(int)
    steps["has_prices"] = len(ev)
    ev["f_idx"] = dates.searchsorted(ev["filing_date"].to_numpy(), side="left")
    ev["t_idx"] = dates.searchsorted(ev["trans_date"].to_numpy(), side="left")
    ev = ev[(ev["f_idx"] < len(dates)) & (ev["t_idx"] < len(dates))]

    ok, adv, dd = [], [], []
    w, look = u["adv_window"], s["drop_lookback"]
    for t, k, ti, fi, price in zip(
        ev["ticker"], ev["k"], ev["t_idx"], ev["f_idx"], ev["price"], strict=True
    ):
        raw = mkt.raw_close.get(t)
        close = float(raw.get(dates[ti], np.nan)) if raw is not None else np.nan
        ok.append(price_matches(close, price, u["price_match_tolerance"], t in mkt.no_split_info))
        lo = max(0, fi - w + 1)
        seg_dv = mkt.dollar_volume[lo : fi + 1, k]
        adv.append(float(np.nanmedian(seg_dv)) if np.isfinite(seg_dv).any() else np.nan)
        if ti - look >= mkt.first_valid[k] and mkt.first_valid[k] >= 0:
            seg = mkt.returns[ti - look + 1 : ti + 1, k]
            dd.append(
                float(np.nanprod(1 + seg) - 1) if np.isfinite(seg).sum() > look // 2 else np.nan
            )
        else:
            dd.append(np.nan)
    ev["price_ok"], ev["adv_usd"], ev["prior_return"] = ok, adv, dd
    ev = ev[ev["price_ok"]]
    steps["ticker_check_passed"] = len(ev)
    ev = ev[ev["adv_usd"] >= u["min_adv_usd"]]
    steps["liquid_enough"] = len(ev)
    return ev.reset_index(drop=True), steps


def one_way_cost(adv_usd: np.ndarray, cfg: dict, multiplier: float = 1.0) -> np.ndarray:
    c = cfg["costs"]
    base = c["commission_bps"] + c["fx_bps"]
    spread = np.zeros(len(adv_usd))
    assigned = np.zeros(len(adv_usd), dtype=bool)
    for tier in sorted(c["half_spread_bps"], key=lambda x: -x["min_adv_usd"]):
        m = (~assigned) & (adv_usd >= tier["min_adv_usd"])
        spread[m] = tier["bps"]
        assigned |= m
    return multiplier * (base + spread) / 1e4


def leg_returns(
    ev: pd.DataFrame,
    mkt: Market,
    lag: int,
    horizon: int,
    cost: np.ndarray,
    delist_return: float,
    t_end: int | None = None,
) -> dict[str, np.ndarray]:
    """Daily return, open-position count and excess return of one leg."""
    t_len = len(mkt.dates) if t_end is None else t_end
    total = np.zeros(t_len)
    count = np.zeros(t_len)
    entries = (ev["f_idx"].to_numpy() + lag).astype(int)
    ks = ev["k"].to_numpy()
    order = np.lexsort((entries, ks))
    i = 0
    n = len(order)
    n_hold = 0
    while i < n:
        j = order[i]
        k, e, c = ks[j], entries[j], cost[j]
        x = e + horizon
        i += 1
        while i < n and ks[order[i]] == k and entries[order[i]] <= x:  # extend the holding
            x = max(x, entries[order[i]] + horizon)
            i += 1
        start = e + 1
        if start >= t_len:
            continue
        end = min(x, t_len - 1)
        lv = mkt.last_valid[k]
        if lv < start:  # no price after entry: cannot be held
            continue
        r = mkt.returns[start : end + 1, k].copy()
        if lv < end:  # the price series stops inside the holding period: delisted
            r = np.append(r[: max(lv - start + 1, 0)], delist_return)
        if not len(r):
            continue
        r = np.where(np.isfinite(r), r, 0.0)
        r[0] -= c
        r[-1] -= c
        total[start : start + len(r)] += r
        count[start : start + len(r)] += 1
        n_hold += 1
    port = np.divide(total, count, out=np.zeros(t_len), where=count > 0)
    excess = np.where(count > 0, port - mkt.bench[:t_len], 0.0)
    return {"port": port, "count": count, "excess": excess, "n_holdings": n_hold}


def leg_masks(ev: pd.DataFrame, cfg: dict) -> dict[str, np.ndarray]:
    s = cfg["signal"]
    return {
        "all": np.ones(len(ev), dtype=bool),
        "opportunistic": (ev["trader_class"] == "opportunistic").to_numpy(),
        "routine": (ev["trader_class"] == "routine").to_numpy(),
        "cluster": (ev["cluster_n"] >= s["cluster_min_insiders"]).to_numpy(),
        "single": (ev["cluster_n"] == 1).to_numpy(),
        "postdrop": (ev["prior_return"] <= s["drop_threshold"]).to_numpy(),
        "nodrop": (ev["prior_return"] > s["drop_threshold"]).to_numpy(),
        "large": (ev["frac_increase"] >= s["large_increase"]).to_numpy(),
        "small": (ev["frac_increase"] < s["large_increase"]).to_numpy(),
    }
