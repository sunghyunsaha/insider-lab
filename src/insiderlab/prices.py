"""Daily prices and USD/KRW from free sources, cached per ticker.

Providers (tried in order, see ``prices.providers`` in the config):

* ``yfinance``  Yahoo Finance via the yfinance package: adjusted and unadjusted close,
                volume and splits. Delisted tickers are usually missing (survivorship bias).
* ``stooq``     stooq.com daily CSV: split-adjusted close and volume, no split history.
* ``tiingo``    used first when ``TIINGO_API_KEY`` is set; covers many delisted tickers.

Each ticker is cached as ``data/prices/<TICKER>.parquet`` with columns
``close`` (as traded, split-adjusted where the source only offers that), ``adj_close``
(split- and dividend-adjusted), ``volume`` and ``split`` (split ratio on that day, 1 if none).
Tickers no provider could serve are listed in ``data/prices/_missing.json`` with the
reason, so the report can say how many events were lost and why.
"""

from __future__ import annotations

import io
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["close", "adj_close", "volume", "split"]


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-").replace("/", "-")


def stooq_symbol(ticker: str) -> str:
    return ticker.replace(".", "-").replace("/", "-").lower() + ".us"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in COLUMNS:
        if c not in df:
            df[c] = 1.0 if c == "split" else np.nan
    df["split"] = df["split"].replace(0, 1.0).fillna(1.0)
    df = df[COLUMNS].astype(float)
    return df[df["adj_close"].notna() & (df["adj_close"] > 0)]


def fetch_yfinance(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    symbols = {yahoo_symbol(t): t for t in tickers}
    raw = yf.download(
        list(symbols),
        start=start,
        auto_adjust=False,
        actions=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    for sym, t in symbols.items():
        try:
            sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        sub = sub.dropna(how="all")
        if sub.empty or "Adj Close" not in sub:
            continue
        df = pd.DataFrame(
            {
                "close": sub.get("Close"),
                "adj_close": sub.get("Adj Close"),
                "volume": sub.get("Volume"),
                "split": sub.get("Stock Splits", pd.Series(1.0, index=sub.index)),
            }
        )
        df = _clean(df)
        if len(df):
            out[t] = df
    return out


def fetch_stooq(tickers: list[str], start: str, pause: float = 0.5) -> dict[str, pd.DataFrame]:
    import requests

    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol(t)}&i=d"
        try:
            resp = requests.get(url, timeout=30)
        except requests.RequestException:
            continue
        text = resp.text
        if resp.status_code != 200 or not text.startswith("Date"):
            continue
        df = pd.read_csv(io.StringIO(text), parse_dates=["Date"], index_col="Date")
        df = df[df.index >= pd.Timestamp(start)]
        df = _clean(
            pd.DataFrame(
                {"close": df["Close"], "adj_close": df["Close"], "volume": df.get("Volume")}
            )
        )
        if len(df):
            out[t] = df
        time.sleep(pause)
    return out


def fetch_tiingo(tickers: list[str], start: str, token: str, pause: float = 0.3):
    import requests

    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        url = f"https://api.tiingo.com/tiingo/daily/{yahoo_symbol(t).lower()}/prices"
        try:
            resp = requests.get(url, params={"startDate": start, "token": token}, timeout=30)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        rows = resp.json()
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["date"])
        df = _clean(
            pd.DataFrame(
                {
                    "close": df["close"],
                    "adj_close": df["adjClose"],
                    "volume": df["volume"],
                    "split": df["splitFactor"],
                }
            )
        )
        if len(df):
            out[t] = df
        time.sleep(pause)
    return out


def update_cache(
    tickers: Iterable[str],
    cache: Path,
    providers: list[str],
    start: str,
    batch_size: int = 100,
    refresh: bool = False,
    log=print,
) -> dict[str, int]:
    """Fetch every ticker not yet cached (or all, with ``refresh``)."""
    cache.mkdir(parents=True, exist_ok=True)
    missing_path = cache / "_missing.json"
    missing = json.loads(missing_path.read_text()) if missing_path.exists() else {}
    todo = sorted({t for t in tickers if refresh or not (cache / f"{t}.parquet").exists()})
    if not refresh:
        todo = [t for t in todo if t not in missing]
    token = os.environ.get("TIINGO_API_KEY", "").strip()
    order = (["tiingo"] if token else []) + [p for p in providers if p != "tiingo"]
    stats = {"requested": len(todo), "fetched": 0, "missing": 0}
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        left = list(batch)
        for prov in order:
            if not left:
                break
            try:
                if prov == "yfinance":
                    got = fetch_yfinance(left, start)
                elif prov == "stooq":
                    got = fetch_stooq(left, start)
                elif prov == "tiingo":
                    got = fetch_tiingo(left, start, token)
                else:
                    raise ValueError(f"unknown provider {prov}")
            except Exception as exc:  # a provider outage must not stop the run
                log(f"  {prov} failed on a batch: {type(exc).__name__}: {exc}")
                got = {}
            for t, df in got.items():
                df.attrs["source"] = prov
                df.assign(source=prov).to_parquet(cache / f"{t}.parquet")
            left = [t for t in left if t not in got]
            stats["fetched"] += len(got)
        for t in left:
            missing[t] = "no provider returned data"
        stats["missing"] += len(left)
        log(
            f"  prices {min(i + batch_size, len(todo))}/{len(todo)}: "
            f"{stats['fetched']} fetched, {stats['missing']} missing"
        )
        missing_path.write_text(json.dumps(missing, indent=0, sort_keys=True))
    return stats


def load_panel(tickers: Iterable[str], cache: Path) -> dict[str, pd.DataFrame]:
    """Cached price frames for the requested tickers (absent ones are skipped)."""
    out = {}
    for t in sorted(set(tickers)):
        f = cache / f"{t}.parquet"
        if f.exists():
            out[t] = pd.read_parquet(f)
    return out


def fetch_fx(series: str, cache: Path) -> pd.Series:
    """FRED series (e.g. DEXKOUS, KRW per USD), cached as ``fx_<series>.parquet``."""
    import requests

    path = cache / f"fx_{series}.parquet"
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "value"]
    s = pd.to_numeric(df["value"], errors="coerce")
    s.index = pd.to_datetime(df["date"])
    s = s.dropna().rename(series)
    cache.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(path)
    return s


def load_fx(series: str, cache: Path) -> pd.Series:
    path = cache / f"fx_{series}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `insiderlab fetch-prices` first")
    return pd.read_parquet(path)[series]


def unadjusted_close(df: pd.DataFrame) -> pd.Series:
    """Close as it traded on each day: undo splits that happened later.

    Tiingo's ``close`` is already as traded; Yahoo's is split-adjusted with the split
    history alongside; Stooq gives no split history, so its close is returned as is and
    the ticker check falls back to common split ratios (``backtest.price_matches``).
    """
    if "source" in df and len(df) and df["source"].iloc[0] == "tiingo":
        return df["close"]
    split = df["split"].replace(0, 1.0).fillna(1.0)
    later = split[::-1].cumprod()[::-1].shift(-1).fillna(1.0)  # product of splits after t
    return df["close"] * later


def reachability() -> dict[str, str]:
    """Quick check of every external host the pipeline needs."""
    import requests

    ua = os.environ.get("SEC_USER_AGENT", "insider-lab check@example.com")
    checks = {
        "sec": ("https://www.sec.gov/files/insider_transactions_readme.pdf", {"User-Agent": ua}),
        "fred": ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS", {}),
        "stooq": ("https://stooq.com/q/d/l/?s=spy.us&i=d", {}),
        "yahoo": (
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=5d",
            {"User-Agent": "Mozilla/5.0"},
        ),
    }
    out = {}
    for name, (url, headers) in checks.items():
        try:
            r = requests.get(url, headers=headers, timeout=20)
            out[name] = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except Exception as exc:  # report, do not raise
            out[name] = f"failed: {type(exc).__name__}"
    return out
