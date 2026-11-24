import numpy as np
import pandas as pd

from insiderlab.backtest import (
    Market,
    attach_price_features,
    build_market,
    leg_returns,
    one_way_cost,
    price_matches,
)

CFG = {
    "costs": {
        "commission_bps": 10,
        "fx_bps": 5,
        "half_spread_bps": [
            {"min_adv_usd": 50_000_000, "bps": 5},
            {"min_adv_usd": 10_000_000, "bps": 15},
            {"min_adv_usd": 0, "bps": 40},
        ],
    },
    "universe": {"adv_window": 5, "price_match_tolerance": 0.25, "min_adv_usd": 1_000_000},
    "signal": {"drop_lookback": 5},
}


def _market(t_len=40, k_len=2, r=0.01, bench=0.0):
    dates = pd.bdate_range("2020-01-01", periods=t_len)
    rets = np.full((t_len, k_len), r)
    rets[0] = np.nan
    return Market(
        dates=dates,
        tickers=[f"K{i}" for i in range(k_len)],
        returns=rets,
        last_valid=np.full(k_len, t_len - 1),
        first_valid=np.zeros(k_len, dtype=int),
        dollar_volume=np.full((t_len, k_len), 2e7),
        bench=np.full(t_len, bench),
        raw_close={},
        no_split_info=set(),
    )


def _events(rows):
    return pd.DataFrame(rows, columns=["k", "f_idx"])


def test_single_holding_window_and_costs():
    mkt = _market()
    ev = _events([(0, 5)])
    out = leg_returns(ev, mkt, lag=1, horizon=10, cost=np.array([0.001]), delist_return=0.0)
    held = np.flatnonzero(out["count"])
    assert held[0] == 7 and held[-1] == 16  # entry at close of day 6, held 10 days
    assert abs(out["port"][7] - (0.01 - 0.001)) < 1e-12  # entry cost
    assert abs(out["port"][16] - (0.01 - 0.001)) < 1e-12  # exit cost
    assert abs(out["port"][10] - 0.01) < 1e-12
    assert out["excess"][3] == 0.0  # no position: excess is zero


def test_repeat_event_extends_instead_of_doubling():
    mkt = _market()
    ev = _events([(0, 5), (0, 10)])
    out = leg_returns(ev, mkt, lag=1, horizon=10, cost=np.zeros(2), delist_return=0.0)
    assert out["n_holdings"] == 1
    assert out["count"].max() == 1
    assert np.flatnonzero(out["count"])[-1] == 21


def test_equal_weight_across_positions():
    mkt = _market()
    mkt.returns[:, 1] = -0.01
    ev = _events([(0, 5), (1, 5)])
    out = leg_returns(ev, mkt, lag=1, horizon=10, cost=np.zeros(2), delist_return=0.0)
    assert abs(out["port"][10]) < 1e-12 and out["count"][10] == 2


def test_delisting_return_applied_once():
    mkt = _market()
    mkt.last_valid[0] = 12
    mkt.returns[13:, 0] = np.nan
    ev = _events([(0, 5)])
    out = leg_returns(ev, mkt, lag=1, horizon=10, cost=np.zeros(1), delist_return=-0.3)
    assert abs(out["port"][13] + 0.3) < 1e-12
    assert out["count"][14] == 0


def test_truncation_at_t_end():
    mkt = _market()
    ev = _events([(0, 5)])
    out = leg_returns(ev, mkt, lag=1, horizon=30, cost=np.zeros(1), delist_return=0.0, t_end=20)
    assert len(out["port"]) == 20 and out["count"][-1] == 1


def test_costs_by_liquidity():
    c = one_way_cost(np.array([1e8, 2e7, 2e6]), CFG)
    assert np.allclose(c, [0.0020, 0.0030, 0.0055])
    assert np.allclose(one_way_cost(np.array([1e8]), CFG, 2.0), [0.004])


def test_price_match_with_and_without_splits():
    assert price_matches(10.5, 10.0, 0.25, False)
    assert not price_matches(5.0, 10.0, 0.25, False)
    assert price_matches(5.0, 10.0, 0.25, True)  # 2:1 split, no split history


def test_build_market_and_features_drop_mismatched_ticker():
    dates = pd.bdate_range("2020-01-01", periods=60)
    px = pd.Series(np.linspace(20, 30, 60), index=dates)
    good = pd.DataFrame(
        {"close": px, "adj_close": px, "volume": 1e6, "split": 1.0, "source": "yfinance"}
    )
    bench = pd.DataFrame({"adj_close": pd.Series(100.0, index=dates)})
    mkt = build_market({"GOOD": good, "BAD": good.copy()}, bench, "2020-01-01")
    ev = pd.DataFrame(
        {
            "ticker": ["GOOD", "BAD"],
            "filing_date": [dates[20], dates[20]],
            "trans_date": [dates[18], dates[18]],
            "price": [float(px.iloc[18]), float(px.iloc[18]) * 3.7],  # BAD: wrong company
        }
    )
    out, steps = attach_price_features(ev, mkt, CFG)
    assert list(out["ticker"]) == ["GOOD"]
    assert steps["has_prices"] == 2 and steps["ticker_check_passed"] == 1
    assert out["adv_usd"].iloc[0] > 1e7
    assert out["prior_return"].iloc[0] > 0
