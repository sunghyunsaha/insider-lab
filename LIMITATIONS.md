# Limitations

What the backtest cannot tell you, roughly in order of how much it matters.

1. **Survivorship bias in prices.** Yahoo and Stooq mostly drop delisted tickers. Events in
   companies that later went bankrupt or were delisted are therefore missing from the
   backtest, which flattens the left tail and flatters every leg. The funnel in the report
   shows how many events were lost at the "has prices" step. Fix: CRSP via WRDS, or Tiingo
   (set `TIINGO_API_KEY`), which covers more delisted names.
2. **Ticker reuse.** The SEC data gives the ticker at filing time; a free price source
   gives today's owner of that ticker. The 25% price check drops most mismatches, not all.
3. **No acceptance time.** Entry waits until the close of the next trading day. Part of the
   price reaction is missed by design; the real Toss user, acting the next KST morning,
   is in roughly the same position.
4. **Modelled costs.** Commission and FX follow Toss's published rates; the half-spread by
   liquidity bucket is an assumption, not a measurement. Results at 0x and 2x costs bracket
   it.
5. **Whole shares.** The backtest holds fractional equal weights. On Toss many small and
   mid caps cannot be bought fractionally, so a small account cannot replicate the
   portfolio; at about 1.5M KRW a single share can exceed the 5% per-stock limit.
6. **Benchmark proxy.** SPY total return stands in for TIGER S&P 500 (fees, tracking
   difference and Korean fund taxation are not modelled day by day).
7. **No factor adjustment yet.** Excess returns are over SPY, not over a size, value and
   momentum model. Insider purchases lean towards small and value stocks, so part of any
   excess may be factor exposure rather than information.
8. **Heuristic exclusions.** Funds, SPACs and BDCs are removed by issuer name; some slip
   through and some operating companies may be wrongly removed.
9. **Data quality.** The SEC warns that its data sets are as filed and may contain errors.
   Obvious errors (non-positive shares or prices) are dropped; others are not detected.
10. **Live trading cannot validate the edge.** At a few dozen trades a year, a 1% average
    excess per trade with 15% noise needs about 900 trades to show at t = 2. The ledger
    checks calibration and process, not alpha.
