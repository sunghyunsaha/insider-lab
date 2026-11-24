# Investment policy (template: Saha edits, Claude proposes)

Draft 2026-11-25. Changes take effect on the first day of the following month and are
logged at the bottom with the date and the reason. This is a personal rulebook for
research and decisions, not financial advice.

## 1. Purpose

- The core (TIGER S&P 500) is the default home for money. It is held for decades.
- The insider-signal work is first a research and career project. Real money follows
  evidence, not the other way round.

## 2. Benchmark

TIGER S&P 500, measured in KRW, after costs and Korean tax. Every idea, every month, is
compared with "what if this money had stayed in the core".

## 3. Sizing

| Rule | Limit |
| --- | --- |
| Core | at least 85% of the portfolio |
| Active sleeve (all single stocks together) | at most 15% |
| Any one stock | at most 5% |
| Leverage, options, margin, short selling | never |

## 4. Gate before any real money goes into the signal

1. Backtest: deflated Sharpe ratio at least 0.95 and PBO below 0.2 on the pre-registered
   tests, and a positive result on the held-out years.
2. Six months of paper trading in `ledger/ledger.csv`, with the scorecard showing the
   stated probabilities are not overconfident (Brier score below 0.25).
3. A written note in DECISIONS.md that both conditions were met.

Until then the signal runs on paper only.

## 5. Before any real trade

1. **Monthly session only.** Buy and sell decisions happen in one session in the first
   week of the month, never from a daily feed or an alert.
2. **Pre-mortem, committed to git**: thesis in one sentence, the main risk, what would
   show the thesis is wrong, the exit rule (time or event), and the size as % of the
   portfolio.
3. **24-hour wait** between committing the pre-mortem and placing the order.
4. **At most two new positions a month.**
5. **No averaging down** without a new written thesis that would justify buying today at
   that size.
6. **No new trade within 48 hours of closing a position at a loss.**
7. Orders: limit orders in the regular US session only (23:30 to 06:00 KST in winter,
   22:30 to 05:00 in summer). FX converted in weekday 09:00 to 15:30 KST.

## 6. Existing positions (NMM, IBM, NVDA, MRVL)

Reviewed under this policy at the first monthly session. The test for each: would I buy
it today, at this size, with a written thesis? Past cost is not part of that test. This
project triggers no action before that session.

## 7. Reviews

| When | What |
| --- | --- |
| Monthly | Scorecard (`insiderlab ledger score`), positions against the limits above, any pre-mortems due |
| Quarterly | This policy, the tax rules in docs/TAX.md, the cost assumptions in the config |
| Yearly | Whether the project is still worth the time |

## Change log

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-25 | First draft | Phase 0 design memo |
