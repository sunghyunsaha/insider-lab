# Decisions log

Every choice that could change a result, with the date and the reason. Changes to the
hypotheses or the config after 2026-11-25 are new trials and must be listed here.

| # | Date | Decision | Reason |
| --- | --- | --- | --- |
| D1 | 2026-11-25 | Build the medium architecture from the Phase 0 memo, starting with the historical backtest. | Saha accepted the memo's defaults. |
| D2 | 2026-11-25 | Main goal: research and career project first; real money only after the gate in POLICY.md. | Memo decision 1 and 2, defaults accepted. |
| D3 | 2026-11-25 | Weekly digest plus alerts, no daily brief, and no scheduled task until the backtest has been read. | Memo decision 3. The signal plays out over months, and a daily feed invites over-trading. |
| D4 | 2026-11-25 | Free price data first (Yahoo via yfinance, Stooq as fallback, Tiingo when a key is set). WRDS/CRSP replaces it if Yonsei offers access. | Memo decision 4. Known cost: delisted firms are mostly missing. |
| D5 | 2026-11-25 | Universe: officers and directors, price at least $5, purchase at least $25k, 20-day median dollar volume at least $1M, no funds, SPACs or BDCs. Market cap is not filtered directly because the free data has no point-in-time shares outstanding; dollar volume is the liquidity screen instead. | Memo decision 5, adapted to the data. |
| D6 | 2026-11-25 | Delisting return: 0% in the primary run, -30% as sensitivity (the memo proposed -30% as default). | Without delisting codes, mergers (usually at a premium) and failures cannot be told apart; -30% on every stopped series would bias the result down as surely as 0% biases it up. Both are reported. |
| D7 | 2026-11-25 | Entry at the close of the first trading day after FILING_DATE (lag 1), not on the filing day. | The data sets have the filing date but not the acceptance time; many filings arrive after the close. |
| D8 | 2026-11-25 | Holdout 2024-01-01 onwards stays locked in the first run. | Lets Saha read the in-sample result and freeze the plan before the one look at fresh data. |
| D9 | 2026-11-25 | Public repo; the ledger holds the system's claims only, never Saha's holdings. | Memo decision 8. |
| D10 | 2026-11-25 | Benchmark: SPY total return in USD as the proxy for TIGER S&P 500. TIGER's own fee and tracking difference are not modelled. | No free daily history of the TIGER ETF in this pipeline; both are unhedged S&P 500 exposure, so USD/KRW moves them together. |
