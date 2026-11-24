# Specification

Version 0.1, 2026-11-25. Owner: Saha (Sunghyun Hur). Built with Claude.

## 1. Goal

A long-term decision-support system around insider-trading patterns, whose reliability is
measured rather than asserted. In priority order:

1. Answer, on history and with honest statistics, whether insider-purchase signals beat
   the S&P 500 after costs, FX and Korean tax for a small long-only investor.
2. Keep every forward-looking claim the system makes in an append-only ledger and score it
   for calibration and for return versus the benchmark.
3. Support decisions with rules (POLICY.md) that guard against the behaviour that actually
   cost money: buying after run-ups, sunk-cost holding, revenge trading, over-trading.

Non-goals: trading automatically, giving instructions, leverage, options, margin.

## 2. Data

| Data | Source | Notes |
| --- | --- | --- |
| Insider transactions | SEC Insider Transactions Data Sets, quarterly zips, 2006 onwards | Tables SUBMISSION, REPORTINGOWNER, NONDERIV_TRANS; dates DD-MON-YYYY; AFF10B5ONE (10b5-1 checkbox) from 2023 |
| Daily prices | yfinance (Yahoo), Stooq, Tiingo if `TIINGO_API_KEY` is set | Cached per ticker under `data/prices/`; missing tickers logged |
| Benchmark | SPY adjusted close | Total-return proxy for TIGER S&P 500 |
| USD/KRW | FRED DEXKOUS | Noon buying rate, New York |
| Holdings | Manual monthly export from Toss | Never committed (`data/holdings/` is git-ignored) |

Signal date is always FILING_DATE, never the trade date.

## 3. Backtest

- Events: one per original Form 4 purchase filing that passes the population filters in
  HYPOTHESES.md.
- Legs: all, opportunistic, routine, cluster, single, postdrop, nodrop, large, small.
- Specifications: lag 1 or 2 trading days after the filing date (entry at close), hold 63
  or 126 trading days. Primary: lag 1, 126 days.
- Portfolio: equal weight across open positions, daily; a repeat event extends a holding.
- Costs (one-way): 10 bp commission + 5 bp FX + half-spread of 5, 15 or 40 bp by 20-day
  median dollar volume (at least $50M, $10M, otherwise). Sensitivity at 0x and 2x.
- Delisting: a series that stops before the exit gets 0% (primary) or -30% (sensitivity).
- In-sample 2009-01-01 to 2023-12-31; holdout 2024 onwards, locked.

## 4. Statistics

Pre-registered one-sided tests with Newey-West t-statistics; Holm and BH over the five
confirmatory hypotheses; sub-period sign check; deflated Sharpe ratio and PBO (CSCV, 16
blocks) over the 36-series trial matrix; effective number of trials. All computed by
overfit-lab (pinned commit in requirements.txt).

## 5. Prediction ledger

`ledger/ledger.csv` and `ledger/resolutions.csv`, append-only, enforced in CI. Claims are
probabilities that a ticker beats or trails SPY in KRW over a horizon. Scoring: hit rate,
Brier score, log loss, calibration by probability bin, mean signed excess in KRW.
Schema: [ledger/SCHEMA.md](ledger/SCHEMA.md).

## 6. Briefs (not scheduled yet)

Per memo decision 3: a weekly digest (Saturday about 07:43 KST) plus push alerts only for
filings on Saha's holdings or clusters rated Strong; a monthly scorecard. The daily brief
spec from the project brief is kept below for reference and is off by default.

Every brief: each fact dated and sourced; facts kept apart from inference; filing age
stated; each idea has a one-line thesis, the main risk and what would invalidate it; no
price targets; every claim logged in the ledger with probability and horizon; ends with
the line "Research only, not financial advice; the decisions are yours."

If Anthropic (ticker ANT) appears in the data: facts only, a disclosure that the brief is
written by an Anthropic model, no analysis.

Signal quality labels used in briefs:

| Label | Meaning |
| --- | --- |
| Strong | Matches a hypothesis that passed its pre-registered test, opportunistic or clustered, liquid, filing at most 5 days old, no offering or 10b5-1 flag |
| Moderate | Matches the literature's pattern but not a passed hypothesis yet, or one caveat |
| Weak | Routine trader, small value, or several caveats |
| Likely noise | Fund or SPAC, controlling-holder block, offering participation, family trading both ways |

## 7. Environment

Code runs on Windows and Linux (CI tests both). Data download needs network access to
sec.gov, fred.stlouisfed.org and a price host; the GitHub Actions `Research run` workflow
does the full run and commits the generated reports.
