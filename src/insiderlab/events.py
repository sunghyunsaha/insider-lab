"""Turn normalised Form 4 transactions into dated purchase events with pre-registered features.

Every feature uses only information available on the event's FILING_DATE:

* routine / opportunistic (Cohen, Malloy & Pomorski 2012): an insider is *classified* if
  they traded (open-market purchase or sale) in each of the three calendar years before
  the trade; a classified insider is *routine* if those trades fell in the same calendar
  month as this trade in all three years, otherwise *opportunistic*.
* cluster: number of distinct insiders whose purchases of the same issuer were FILED in
  the 30 calendar days up to and including this filing date (no look-ahead).
* size: shares bought relative to shares held before the purchase.

Price-based features (prior drawdown, liquidity, ticker check) are added in
``backtest.attach_price_features`` once prices are loaded.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

NON_COMMON = re.compile(
    r"PREFERRED|\bPFD\b|NOTE|WARRANT|\bUNITS?\b|DEBENTURE|\bRIGHTS?\b|BOND|DEPOSITARY|OPTION",
    re.IGNORECASE,
)


TICKER_OK = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
NOT_TICKERS = {"NONE", "NA", "N.A", "N-A", "N", "NULL", "TBD"}


def clean_ticker(raw: str) -> str:
    """Normalise the issuer's self-reported ticker: '(AIG)' -> 'AIG', "BF'B" -> 'BF.B'.

    Returns '' when the result does not look like a US ticker (e.g. '--', '* BTC',
    'N/A', several tickers in one field).
    """
    t = str(raw or "").upper().strip()
    t = re.sub(r"[()\[\]`*\s]", "", t)
    t = t.replace("'", ".").replace("/", ".")
    t = t.split(";")[0].split(",")[0]
    if t in NOT_TICKERS or not TICKER_OK.match(t):
        return ""
    return t


def open_market_trades(tx: pd.DataFrame) -> pd.DataFrame:
    """Open-market purchases (P) and sales (S) on original Form 4 filings, common stock only."""
    df = tx[(tx["form"] == "4") & tx["code"].isin(["P", "S"])].copy()
    df = df[~df["security_title"].fillna("").str.contains(NON_COMMON)]
    df = df[df["trans_date"].notna() & df["filing_date"].notna()]
    return df


def purchase_events(tx: pd.DataFrame, signal: dict | None = None) -> pd.DataFrame:
    """One event per purchase filing (an insider can report several lots on one form)."""
    signal = signal or {}
    trades = open_market_trades(tx)
    buys = trades[
        (trades["code"] == "P")
        & (trades["acq_disp"] == "A")
        & (trades["shares"] > 0)
        & (trades["price"] > 0)
        & (~trades["equity_swap"])
    ].copy()
    buys["value"] = buys["shares"] * buys["price"]
    g = buys.groupby("accession", sort=False)
    ev = g.agg(
        filing_date=("filing_date", "first"),
        trans_date=("trans_date", "min"),
        trans_date_last=("trans_date", "max"),
        issuer_cik=("issuer_cik", "first"),
        issuer_name=("issuer_name", "first"),
        ticker=("ticker", "first"),
        owner_cik=("owner_cik", "first"),
        owner_name=("owner_name", "first"),
        owner_title=("owner_title", "first"),
        n_owners=("n_owners", "first"),
        is_officer=("is_officer", "first"),
        is_director=("is_director", "first"),
        is_ten_pct=("is_ten_pct", "first"),
        plan_10b5_1=("plan_10b5_1", "max"),
        shares=("shares", "sum"),
        value=("value", "sum"),
        owned_after=("owned_after", "max"),
    ).reset_index()
    ev["price"] = ev["value"] / ev["shares"]
    before = ev["owned_after"] - ev["shares"]
    ev["frac_increase"] = np.where(before > 0, ev["shares"] / before.where(before > 0), np.inf)
    ev["filing_lag_days"] = (ev["filing_date"] - ev["trans_date_last"]).dt.days
    ev["ticker"] = ev["ticker"].map(clean_ticker)
    ev = ev[ev["ticker"] != ""]
    ev = classify_routine(ev, trades, signal.get("routine_years", 3))
    ev = add_clusters(ev, signal.get("cluster_window_days", 30))
    return ev.sort_values(["filing_date", "accession"]).reset_index(drop=True)


def classify_routine(ev: pd.DataFrame, trades: pd.DataFrame, years: int = 3) -> pd.DataFrame:
    """Add ``trader_class`` in {routine, opportunistic, unclassified} (vectorised).

    Keys are integers: owner code * 10_000 + year, and that * 100 + month.
    """
    hist = trades[["owner_cik", "trans_date"]].dropna()
    codes, uniques = pd.factorize(
        pd.concat([hist["owner_cik"], ev["owner_cik"]], ignore_index=True).astype(str)
    )
    hc, ec = codes[: len(hist)].astype("int64"), codes[len(hist) :].astype("int64")
    y_keys = np.unique(hc * 10_000 + hist["trans_date"].dt.year.to_numpy())
    ym_keys = np.unique(
        (hc * 10_000 + hist["trans_date"].dt.year.to_numpy()) * 100
        + hist["trans_date"].dt.month.to_numpy()
    )
    year = ev["trans_date"].dt.year.to_numpy()
    month = ev["trans_date"].dt.month.to_numpy()
    classified = ec >= 0
    routine = ec >= 0
    for k in range(1, years + 1):
        yk = ec * 10_000 + (year - k)
        classified &= np.isin(yk, y_keys)
        routine &= np.isin(yk * 100 + month, ym_keys)
    cls = np.where(classified, np.where(routine, "routine", "opportunistic"), "unclassified")
    return ev.assign(trader_class=cls)


def add_clusters(ev: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """Distinct insiders filing purchases of the issuer in the window ending at this filing."""
    counts = np.zeros(len(ev), dtype=int)
    for _, idx in ev.groupby("issuer_cik").groups.items():
        sub = ev.loc[idx, ["filing_date", "owner_cik"]].sort_values("filing_date")
        dates = sub["filing_date"].to_numpy()
        owners = sub["owner_cik"].to_numpy()
        lo = np.searchsorted(dates, dates - np.timedelta64(window_days, "D"), side="left")
        hi = np.searchsorted(dates, dates, side="right")  # same-day filings are known
        for j, pos in enumerate(sub.index):
            counts[ev.index.get_loc(pos)] = len(set(owners[lo[j] : hi[j]]))
    return ev.assign(cluster_n=counts)


def apply_population(ev: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict[str, int]]:
    """Filters that need no prices. Returns the population and a count per step."""
    u = cfg["universe"]
    steps = {"purchase_filings": len(ev)}
    if u.get("officer_or_director", True):
        ev = ev[ev["is_officer"] | ev["is_director"]]
        steps["officer_or_director"] = len(ev)
    ev = ev[~ev["plan_10b5_1"]]
    steps["not_10b5_1_plan"] = len(ev)
    ev = ev[ev["price"] >= u["min_price"]]
    steps["price_at_least_min"] = len(ev)
    ev = ev[ev["value"] >= u["min_value_usd"]]
    steps["value_at_least_min"] = len(ev)
    pattern = re.compile(u["exclude_name_regex"], re.IGNORECASE)
    ev = ev[~ev["issuer_name"].fillna("").str.contains(pattern)]
    steps["not_fund_spac_bdc"] = len(ev)
    return ev.reset_index(drop=True), steps
