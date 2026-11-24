# Pre-registered hypotheses

**Registered: 2026-11-25 (KST), before any insider data or price was downloaded for this
project.** The git commit that adds this file is the timestamp. The machine-readable copy is
`src/insiderlab/hypotheses.py`; the parameters are in `configs/base.yaml`.

Any change to these hypotheses, their definitions or the parameters after this commit is a
new trial. It goes in DECISIONS.md with the date and the reason, and the deflated Sharpe
ratio counts it.

## What I already knew when writing this

Honesty about prior knowledge, since it limits how "pre" this registration is:

- The literature (Jeng, Metrick and Zeckhauser 2003; Cohen, Malloy and Pomorski 2012)
  reports positive abnormal returns for insider purchases, about zero for sales, and about
  zero for routine traders. Their samples end in 2007 at the latest; this sample starts
  in 2009.
- Saha's starting point was one case (NMM's CEO buying repeatedly). H5 tests whether that
  kind of repeat buying carries any information.
- I have not seen any SEC insider data or price data for 2009 onwards in this project.

## Population

Original Form 4 filings (not amendments) reporting an open-market purchase (transaction
code P, acquired) of common stock by an officer or director, excluding:

- purchases flagged as made under a Rule 10b5-1 plan (flag available from 2023),
- reported price below $5 or purchase value below $25,000,
- issuers whose names match funds, SPACs or BDCs (heuristic list in the config),
- events whose ticker's market close on the trade date differs from the reported price by
  more than 25% (after undoing later splits): the ticker probably belongs to another
  company now,
- stocks with a 20-day median dollar volume below $1M before entry.

One event per filing. A new event in a ticker the leg already holds extends the holding.

## Timing (no look-ahead)

The signal date is FILING_DATE. The SEC data sets carry the date but not the time of
acceptance, so the primary specification enters at the close of the first trading day
after the filing date (lag 1); lag 2 is a robustness check. Every feature uses only
filings and prices dated on or before the filing date.

## Hypotheses

Each has one primary test, one-sided, on the primary specification: lag 1, 126-trading-day
hold, 1x modelled costs, 0% delisting return, in-sample 2009-01-01 to 2023-12-31.

| ID | Hypothesis | Primary test |
| --- | --- | --- |
| H1 | Open-market purchases by officers and directors beat the S&P 500 after costs. | mean daily excess of leg `all` over SPY > 0 |
| H2 | Opportunistic buyers beat routine buyers. | mean daily (opportunistic minus routine) > 0 |
| H3 | Cluster purchases beat single-insider purchases. | mean daily (cluster minus single) > 0 |
| H4 | Purchases after a drop of 20% or more beat other purchases. | mean daily (postdrop minus nodrop) > 0 |
| H5 | Negative control: routine buyers show no excess return. | passes if mean daily excess of `routine` is NOT significantly > 0 |
| H6 | Purchases that raise the insider's holding by 10% or more beat smaller ones. | mean daily (large minus small) > 0 |

Definitions:

- **Routine / opportunistic** (Cohen, Malloy and Pomorski): an insider is classified if
  they made an open-market purchase or sale in each of the three calendar years before the
  trade. Classified insiders whose trades in those three years all included the same
  calendar month as this trade are routine; the rest are opportunistic. Unclassified
  insiders are in neither leg.
- **Cluster**: at least three distinct insiders filed purchases of the issuer in the 30
  calendar days up to and including this filing date. **Single**: only this insider.
- **Drop**: the stock's total return over the 63 trading days up to the trade date is
  -20% or worse.
- **Large**: shares bought divided by shares held before the purchase is at least 10%
  (a first purchase counts as large).

## Statistics

- Excess returns are daily calendar-time portfolio returns minus SPY (equal-weighted open
  positions; zero excess on days with no position). t-statistics use Newey-West standard
  errors with 10 lags.
- **Confirmatory family**: H1, H2, H3, H4, H6. Holm-adjusted p < 0.05 and a positive
  effect counts as supported. Benjamini-Hochberg is reported alongside.
- **Consistency**: a supported hypothesis must also have the same sign in at least three of
  the four sub-periods (2009-12, 2013-16, 2017-19, 2020-23); otherwise it is reported as
  "supported but unstable".
- **Overfitting**: all 9 legs x 2 lags x 2 horizons = 36 long-only excess series form the
  trial matrix. Reported: deflated Sharpe ratio of the best series (raw and effective
  number of trials), probability of backtest overfitting (CSCV, 16 blocks), survivors
  under Holm and BH.
- **Robustness, not rescue**: other specifications, 0x and 2x costs, and a -30% delisting
  return are reported; none can turn a failed primary test into a pass.

## Holdout

2024-01-01 onwards is not evaluated in the first run. It is opened once, after Saha has read
the in-sample report and recorded in DECISIONS.md that the analysis plan is frozen. Its
result is reported whatever it is.

## What would change real-money policy

Per POLICY.md, real money is considered only if the backtest passes (deflated Sharpe at
least 0.95, PBO below 0.2, positive on the holdout) and then six months of paper trading
in the ledger. Passing the backtest alone is not enough.
