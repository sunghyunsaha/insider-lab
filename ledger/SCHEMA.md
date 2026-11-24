# Prediction ledger

Two append-only CSV files. CI fails any commit that edits or deletes an existing row
(`insiderlab ledger check`). Mistakes are corrected by appending a new claim whose `basis`
says which id it replaces; the old row stays.

## ledger.csv: one row per claim, written when the claim is made

| Field | Meaning |
| --- | --- |
| id | `L-YYYYMMDD-NNN`, unique |
| created_utc | when the row was written (set automatically) |
| author | `system` for claims made by the brief or digest, `saha` for your own |
| ticker | US ticker |
| claim | one plain sentence, e.g. "GNL beats SPY in KRW over 91 days" |
| direction | `+1` beats the benchmark, `-1` trails it |
| horizon_days | calendar days from start_date |
| probability | stated probability that the claim comes true, strictly between 0 and 1 |
| benchmark | `SPY` (proxy for the TIGER S&P 500 core) |
| start_date | first day of the measurement window, YYYY-MM-DD |
| basis | evidence behind it, e.g. "H3 cluster: 7 insiders, newest filing 2026-11-20" |
| filing_age_days | age of the newest filing behind the claim when it was made |
| invalidation | what would show the claim is wrong |

## resolutions.csv: one row per claim once its horizon has passed

| Field | Meaning |
| --- | --- |
| id | the claim's id |
| resolved_utc | when it was scored |
| end_date | start_date + horizon_days |
| ticker_return_krw, benchmark_return_krw | total returns over the window, converted at USD/KRW |
| excess_krw | ticker minus benchmark |
| outcome | 1 if the claim came true (sign of excess matches direction), else 0 |
| price_source | which provider supplied the prices |

## Commands

```bash
insiderlab ledger add --author system --ticker GNL --claim "GNL beats SPY in KRW over 91 days" \
  --direction +1 --horizon 91 --probability 0.55 --basis "H3 cluster, 7 insiders" \
  --filing-age 3 --invalidation "cluster was an equity-offering participation"
insiderlab ledger score   # resolves due claims, writes reports/SCORECARD.md
insiderlab ledger check   # append-only check against the previous commit
```

(The example ticker is illustrative only, not a claim.)
