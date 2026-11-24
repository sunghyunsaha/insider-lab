import subprocess
from datetime import date

import pandas as pd
import pytest

from insiderlab import ledger as L
from insiderlab import tax


def _claim(path, **kw):
    args = dict(
        author="system",
        ticker="ABC",
        claim="ABC beats SPY in KRW over 30 days",
        direction="+1",
        horizon_days=30,
        probability=0.6,
        benchmark="SPY",
        start_date="2026-01-02",
        basis="H3",
        invalidation="offering",
    )
    args.update(kw)
    return L.append_claim(path, **args)


def test_append_and_validate(tmp_path):
    p = tmp_path / "ledger.csv"
    r1 = _claim(p)
    r2 = _claim(p, ticker="XYZ")
    assert r1["id"] != r2["id"]
    with pytest.raises(ValueError, match="probability"):
        _claim(p, probability=1.0)
    with pytest.raises(ValueError, match="direction"):
        _claim(p, direction="2")
    assert len(L.read(p, L.LEDGER_FIELDS)) == 2


def test_resolve_and_score(tmp_path):
    led, res = tmp_path / "ledger.csv", tmp_path / "resolutions.csv"
    _claim(led, ticker="UP")
    _claim(led, ticker="DOWN", probability=0.7)
    _claim(led, ticker="LATER", start_date="2026-12-01")
    idx = pd.bdate_range("2025-12-01", "2026-03-31")
    series = {
        "UP": pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float),
        "DOWN": pd.Series(range(200, 200 - len(idx), -1), index=idx, dtype=float),
        "SPY": pd.Series(100.0, index=idx),
    }
    fx = pd.Series(1400.0, index=idx)
    rows = L.resolve(led, res, lambda t: (series.get(t), "test"), fx, today=date(2026, 3, 1))
    assert {r["id"][-3:] for r in rows} == {"001", "002"}
    outcomes = {r["id"][-3:]: r["outcome"] for r in rows}
    assert outcomes == {"001": "1", "002": "0"}
    card = L.scorecard(led, res, today=date(2026, 3, 1))
    assert card["resolved"] == 2 and card["open"] == 1
    assert abs(card["brier"] - ((0.6 - 1) ** 2 + (0.7 - 0) ** 2) / 2) < 1e-12
    # resolving again appends nothing
    assert L.resolve(led, res, lambda t: (series.get(t), "test"), fx, today=date(2026, 3, 1)) == []


def test_append_only_check(tmp_path):
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    p = repo / "ledger" / "ledger.csv"
    _claim(p)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=repo, check=True)
    _claim(p, ticker="NEW")
    assert "1 row(s) appended" in L.check_append_only(p, "HEAD", repo)
    text = p.read_text().replace("ABC", "ABD")
    p.write_text(text)
    with pytest.raises(SystemExit):
        L.check_append_only(p, "HEAD", repo)


def test_tax_rules():
    assert tax.us_stock_tax(2_000_000) == 0
    assert abs(tax.us_stock_tax(3_500_000) - 220_000) < 1e-6
    assert abs(tax.etf_tax(1_000_000) - 154_000) < 1e-6
    assert tax.etf_tax(1_500_000, "isa") == 0
    assert abs(tax.etf_tax(3_000_000, "isa") - 99_000) < 1e-6
    assert tax.etf_tax(-500_000) == 0
