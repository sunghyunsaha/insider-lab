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


class _LogCapture:
    """Collect yfinance log messages so a rate limit can be detected without internals."""

    def __init__(self):
        import logging

        self.messages: list[str] = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.messages.append(record.getMessage())
        self.logger = logging.getLogger("yfinance")

    def __enter__(self):
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)

    @property
    def rate_limited(self) -> bool:
        text = " ".join(self.messages)
        return any(k in text for k in RATE_LIMIT_MARKERS)


RATE_LIMIT_MARKERS = ("RateLimit", "Rate limited", "Too Many Requests", "HTTP 429")


def fetch_yfinance(tickers: list[str], start: str) -> tuple[dict[str, pd.DataFrame], bool]:
    """Returns the frames it got and whether Yahoo rate-limited the request."""
    import yfinance as yf

    symbols = {yahoo_symbol(t): t for t in tickers}
    with _LogCapture() as cap:
        raw = yf.download(
            list(symbols),
            start=start,
            auto_adjust=False,
            actions=True,
            group_by="ticker",
            threads=False,
            progress=False,
        )
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out, cap.rate_limited
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
    return out, cap.rate_limited


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
    batch_size: int = 50,
    refresh: bool = False,
    retry_missing: bool = False,
    pause: float = 10.0,
    rate_limit_sleep: float = 300.0,
    max_retries: int = 6,
    log=print,
    sleep=time.sleep,
    fetchers: dict | None = None,
) -> dict[str, int]:
    """Fetch every ticker not yet cached, pacing requests and backing off on rate limits.

    ``_missing.json`` maps ticker -> reason. Only ``not_found`` (the provider answered but
    had no data, typically a delisted company) is skipped on later runs; anything else,
    including rate-limited tickers and entries from older versions, is retried.
    Order is preserved, so put the benchmark first.
    """
    cache.mkdir(parents=True, exist_ok=True)
    missing_path = cache / "_missing.json"
    missing = json.loads(missing_path.read_text()) if missing_path.exists() else {}
    seen, todo = set(), []
    for t in tickers:
        if t in seen:
            continue
        seen.add(t)
        if not refresh and (cache / f"{t}.parquet").exists():
            continue
        if not (refresh or retry_missing) and missing.get(t) == "not_found":
            continue
        todo.append(t)
    token = os.environ.get("TIINGO_API_KEY", "").strip()
    order = (["tiingo"] if token else []) + [p for p in providers if p != "tiingo"]
    fetchers = fetchers or {
        "yfinance": fetch_yfinance,
        "stooq": lambda ts, st: (fetch_stooq(ts, st), False),
        "tiingo": lambda ts, st: (fetch_tiingo(ts, st, token), False),
    }
    stats = {"requested": len(todo), "fetched": 0, "not_found": 0, "rate_limited": 0, "backoffs": 0}
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        left, limited = list(batch), False
        for prov in order:
            if not left:
                break
            attempts = 0
            while left:
                try:
                    got, limited = fetchers[prov](left, start)
                except Exception as exc:  # a provider outage must not stop the run
                    log(f"  {prov} failed on a batch: {type(exc).__name__}: {exc}")
                    got, limited = {}, False
                for t, df in got.items():
                    df.assign(source=prov).to_parquet(cache / f"{t}.parquet")
                    missing.pop(t, None)
                stats["fetched"] += len(got)
                left = [t for t in left if t not in got]
                if not (limited and left and attempts < max_retries):
                    break
                wait = min(rate_limit_sleep * 2**attempts, 3600)
                attempts += 1
                stats["backoffs"] += 1
                log(
                    f"  {prov} rate limit: waiting {wait / 60:.0f} min, then retrying "
                    f"{len(left)} tickers (attempt {attempts}/{max_retries})"
                )
                sleep(wait)
            if limited and left:
                break  # do not fall through to another provider and label these missing
        for t in left:
            missing[t] = "rate_limited" if limited else "not_found"
        stats["rate_limited" if limited else "not_found"] += len(left)
        missing_path.write_text(json.dumps(missing, indent=0, sort_keys=True))
        log(
            f"  prices {min(i + batch_size, len(todo))}/{len(todo)}: {stats['fetched']} "
            f"fetched, {stats['not_found']} not found, {stats['rate_limited']} rate-limited"
        )
        if i + batch_size < len(todo):
            sleep(pause)
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
            if r.status_code != 200:  # show the server's stated reason
                out[name] += " | " + " ".join(r.text.split())[:300]
        except Exception as exc:  # report, do not raise
            out[name] = f"failed: {type(exc).__name__}"
    return out
