"""Korean tax on the two legs, as checked on 2026-11-25 (simplified; not tax advice).

* US-listed shares: gains and losses netted over the calendar year; 22% (20% national +
  2% local) on the net gain above a 2.5M KRW basic deduction; FX is part of the KRW gain.
* Korea-listed overseas-index ETF (TIGER S&P 500) in an ordinary account: gains and
  distributions taxed 15.4% as dividend income, no deduction. (The law taxes the lesser
  of the trading gain and the increase in the fund's tax base; this ignores that.)
* The same ETF in an ISA: losses net inside the account, the first 2M KRW (general type)
  is tax-free, 9.9% above that.

Sources are listed in docs/TAX.md. Rules change; re-check them at each quarterly review.
"""

from __future__ import annotations

US_RATE, US_DEDUCTION = 0.22, 2_500_000
ETF_RATE = 0.154
ISA_RATE, ISA_EXEMPT = 0.099, 2_000_000


def us_stock_tax(net_gain_krw: float) -> float:
    return max(0.0, net_gain_krw - US_DEDUCTION) * US_RATE


def etf_tax(gain_krw: float, account: str = "ordinary") -> float:
    if account == "ordinary":
        return max(0.0, gain_krw) * ETF_RATE
    if account == "isa":
        return max(0.0, gain_krw - ISA_EXEMPT) * ISA_RATE
    if account == "pension":
        return 0.0  # deferred until withdrawal; withdrawal tax depends on how it is taken
    raise ValueError(f"unknown account {account!r}")


def after_tax(gain_krw: float, leg: str, account: str = "ordinary") -> float:
    tax = us_stock_tax(gain_krw) if leg == "us_stock" else etf_tax(gain_krw, account)
    return gain_krw - tax
