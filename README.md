# insider-lab: do insider purchases beat the S&P 500, honestly measured?

A research lab for one question: after costs, FX and honest statistics, would following
open-market purchases by US company insiders (SEC Form 4) beat simply holding the S&P 500?
It is built so that "trustworthy" is earned by measurement: hypotheses are dated in git
before any data is seen, every variant tried is counted, and the validation engine is
[overfit-lab](https://github.com/sunghyunsaha/overfit-lab) (deflated Sharpe ratio,
probability of backtest overfitting, Holm and Benjamini-Hochberg).

[![CI](https://github.com/sunghyunsaha/insider-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/sunghyunsaha/insider-lab/actions/workflows/ci.yml)

## Results

<!-- results:start -->
Not run on real data yet. `make demo` runs the whole pipeline on synthetic data with a
planted effect; the research workflow fills this section from `reports/results/`.
<!-- results:end -->

## How it works

```
SEC Insider Transactions Data Sets (quarterly, 2006 onwards)
  -> purchase events (code P, officers and directors, signal date = FILING_DATE)
  -> features known on the filing date: routine vs opportunistic trader, clusters, size
  -> prices (Yahoo / Stooq / Tiingo) -> ticker check, liquidity, prior drawdown
  -> calendar-time portfolios per leg, net of Toss-like costs
  -> 36 excess-return series vs SPY -> overfit-lab diagnostics + pre-registered tests
  -> reports/REPORT.md (every number generated, none typed)
```

| File | What it is |
| --- | --- |
| [HYPOTHESES.md](HYPOTHESES.md) | The six pre-registered hypotheses, dated 2026-11-25, with the exact tests |
| [SPEC.md](SPEC.md) | System specification: data, timing, costs, statistics, ledger, briefs |
| [POLICY.md](POLICY.md) | Personal investment policy template: sizing, the gate to real money, pre-trade rules |
| [DECISIONS.md](DECISIONS.md) | Every choice that could change a result, dated |
| [LIMITATIONS.md](LIMITATIONS.md) | What the backtest cannot tell you |
| [ledger/](ledger/) | Append-only prediction ledger and its schema |
| [docs/TAX.md](docs/TAX.md) | Korean tax rules used in the KRW comparison |

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt && pip install -e . --no-deps
make test        # unit tests, synthetic data, no network
make demo        # full pipeline on synthetic data with a planted effect (seconds)

export SEC_USER_AGENT="insider-lab you@example.com"   # the SEC requires a contact
make data-check  # can this machine reach the SEC, FRED, Stooq and Yahoo?
make data        # SEC data sets, then prices for every event ticker, SPY and USD/KRW
make backtest    # pre-registered backtest -> reports/REPORT.md and this README
```

**Where the real run happens.** The SEC refuses requests from GitHub's servers (HTTP 403,
"Request Rate Threshold Exceeded", DECISIONS D11), so the data download runs on a home PC.
On Windows one command does everything and pushes the generated reports:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Email you@example.com
```

The e-mail goes to the SEC as the contact in the User-Agent header and is never written to
disk. GitHub Actions runs the tests, the ledger check and a reachability check.

## Prediction ledger

```bash
insiderlab ledger add --ticker XYZ --claim "XYZ beats SPY in KRW over 91 days" \
  --direction +1 --horizon 91 --probability 0.55 --basis "H3 cluster" --invalidation "..."
insiderlab ledger score     # monthly: resolves due claims, writes reports/SCORECARD.md
```

Research and education only. Not financial advice; the decisions are the reader's own.
