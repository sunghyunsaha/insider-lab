import json

import numpy as np
import pandas as pd

from insiderlab import prices
from insiderlab.events import clean_ticker


def _frame():
    idx = pd.bdate_range("2020-01-01", periods=5)
    return pd.DataFrame(
        {
            "close": np.arange(5) + 10.0,
            "adj_close": np.arange(5) + 10.0,
            "volume": 1e6,
            "split": 1.0,
        },
        index=idx,
    )


def test_clean_ticker():
    assert clean_ticker("(AIG)") == "AIG"
    assert clean_ticker("[EXP]") == "EXP"
    assert clean_ticker("BF'B") == "BF.B"
    assert clean_ticker("brk.b") == "BRK.B"
    assert clean_ticker("LGF-A") == "LGF-A"
    assert clean_ticker("LTR;CG") == "LTR"  # first of several
    assert clean_ticker("* BTC") == "BTC"
    assert clean_ticker("N O G") == "NOG"  # spaced-out real ticker
    for junk in ("--", "N/A", "(N-A)", "NONE", "", "AXIA3", "RVA:AX"):
        assert clean_ticker(junk) == "", junk


def test_rate_limit_backs_off_and_retries(tmp_path):
    calls, waits = [], []

    def flaky(tickers, start):
        calls.append(list(tickers))
        if len(calls) == 1:  # first call: got one, then Yahoo says stop
            return {tickers[0]: _frame()}, True
        return {t: _frame() for t in tickers if t != "GONE"}, False

    stats = prices.update_cache(
        ["SPY", "AAA", "GONE"],
        tmp_path,
        ["yfinance"],
        "2020-01-01",
        batch_size=10,
        pause=0,
        rate_limit_sleep=60,
        sleep=waits.append,
        log=lambda *a: None,
        fetchers={"yfinance": flaky},
    )
    assert calls[0] == ["SPY", "AAA", "GONE"]  # order kept: benchmark first
    assert calls[1] == ["AAA", "GONE"]
    assert waits[0] == 60
    assert stats["fetched"] == 2 and stats["not_found"] == 1 and stats["rate_limited"] == 0
    missing = json.loads((tmp_path / "_missing.json").read_text())
    assert missing == {"GONE": "not_found"}


def test_still_limited_is_not_labelled_missing(tmp_path):
    def blocked(tickers, start):
        return {}, True

    stats = prices.update_cache(
        ["AAA", "BBB"],
        tmp_path,
        ["yfinance"],
        "2020-01-01",
        pause=0,
        max_retries=2,
        sleep=lambda s: None,
        log=lambda *a: None,
        fetchers={"yfinance": blocked},
    )
    assert stats["rate_limited"] == 2 and stats["backoffs"] == 2
    missing = json.loads((tmp_path / "_missing.json").read_text())
    assert set(missing.values()) == {"rate_limited"}


def test_only_not_found_is_skipped_on_rerun(tmp_path):
    (tmp_path / "_missing.json").write_text(
        json.dumps(
            {
                "OLD": "no provider returned data",  # written by an older version: retry
                "LIM": "rate_limited",
                "DEAD": "not_found",
            }
        )
    )
    seen = []

    def fetch(tickers, start):
        seen.extend(tickers)
        return {t: _frame() for t in tickers}, False

    prices.update_cache(
        ["OLD", "LIM", "DEAD"],
        tmp_path,
        ["yfinance"],
        "2020-01-01",
        pause=0,
        log=lambda *a: None,
        fetchers={"yfinance": fetch},
    )
    assert seen == ["OLD", "LIM"]
    seen.clear()
    prices.update_cache(
        ["DEAD"],
        tmp_path,
        ["yfinance"],
        "2020-01-01",
        pause=0,
        retry_missing=True,
        log=lambda *a: None,
        fetchers={"yfinance": fetch},
    )
    assert seen == ["DEAD"]
