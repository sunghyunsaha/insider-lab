"""Command line: ``insiderlab <command>``. Run from the repository root."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime

import pandas as pd

from . import ledger as L
from . import pipeline, prices, report, sec
from .config import load_config, paths


def _cfg_paths(args):
    p = paths()
    return load_config(args.config, p.root), p


def cmd_data_check(args) -> int:
    for name, status in prices.reachability().items():
        print(f"{name:6s} {status}")
    return 0


def cmd_price_check(args) -> int:
    """Fetch a few known tickers into a scratch cache and check splits and coverage."""
    import tempfile
    from pathlib import Path

    cfg, _ = _cfg_paths(args)
    tickers = ["SPY", "AAPL", "BRK.B", "NVDA", "TWTR"]  # TWTR: delisted 2022
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        stats = prices.update_cache(
            tickers, cache, cfg["prices"]["providers"], "2018-01-01", pause=0
        )
        print(json.dumps(stats))
        panel = prices.load_panel(tickers, cache)
        for t in tickers:
            df = panel.get(t)
            if df is None:
                print(f"{t:6s} missing")
                continue
            print(
                f"{t:6s} {len(df):5d} rows {df.index[0].date()} to {df.index[-1].date()} "
                f"source={df['source'].iloc[0]} splits={int((df['split'] != 1).sum())}"
            )
        aapl = panel.get("AAPL")
        if aapl is not None:
            raw = prices.unadjusted_close(aapl)
            d = pd.Timestamp("2020-08-28")  # last close before the 4-for-1 split
            print(
                f"AAPL 2020-08-28 as traded {raw.get(d, float('nan')):.2f} "
                f"(expected about 499), split-adjusted {aapl['close'].get(d, float('nan')):.2f}"
            )
    fx = prices.fetch_fx(cfg["benchmark"]["fx_series"], Path(tempfile.mkdtemp()))
    print(f"USD/KRW last {fx.index[-1].date()} {fx.iloc[-1]:.1f}")
    return 0


def cmd_fetch_sec(args) -> int:
    cfg, p = _cfg_paths(args)
    first = args.first or cfg["sec"]["first_quarter"]
    last = args.last or cfg["sec"]["last_quarter"] or sec.latest_possible_quarter()
    qs = sec.quarters(first, last)
    print(f"SEC insider data sets {qs[0]} to {qs[-1]} ({len(qs)} quarters)")
    counts = {}
    for q in qs:
        try:
            counts.update(
                sec.build_tables([q], p.sec, p.raw_sec, env_name=cfg["sec"]["user_agent_env"])
            )
            print(f"  {q}: {counts[q]:,} transactions")
        except RuntimeError as exc:
            if q == qs[-1]:  # the newest quarter may not be posted yet
                print(f"  {q}: not available ({exc})")
            else:
                raise
    print(f"total {sum(counts.values()):,} non-derivative transactions")
    return 0


def _population(cfg, p) -> pd.DataFrame:
    tx = sec.load_transactions(p.sec)
    pop, steps = pipeline.prepare_events(tx, cfg)
    for k, v in steps.items():
        print(f"  {k}: {v:,}")
    return pop


def cmd_fetch_prices(args) -> int:
    cfg, p = _cfg_paths(args)
    pop = _population(cfg, p)
    bench = cfg["benchmark"]["ticker"]
    names = sorted(set(pop["ticker"]) - {bench})
    if args.limit:
        names = names[: args.limit]
    tickers = [bench] + names  # benchmark first: without it nothing can be evaluated
    pc = cfg["prices"]
    print(f"fetching prices for {len(tickers):,} tickers (cached ones are skipped)")
    stats = prices.update_cache(
        tickers,
        p.prices,
        pc["providers"],
        cfg["sample"]["history_start"],
        batch_size=pc["batch_size"],
        refresh=args.refresh,
        retry_missing=args.retry_missing,
        pause=pc.get("pause_seconds", 10),
        rate_limit_sleep=pc.get("rate_limit_sleep_seconds", 300),
        max_retries=pc.get("max_retries", 6),
    )
    print(json.dumps(stats))
    fx = prices.fetch_fx(cfg["benchmark"]["fx_series"], p.prices)
    print(f"USD/KRW {fx.index[0].date()} to {fx.index[-1].date()}, last {fx.iloc[-1]:.1f}")
    if not (p.prices / f"{bench}.parquet").exists():
        print(f"{bench} (benchmark) is still missing: run this step again later.")
        return 2
    if stats["rate_limited"]:
        print(
            f"{stats['rate_limited']:,} tickers are still rate-limited. Wait about an hour "
            "and run this step again: it resumes and only fetches what is missing."
        )
        return 2
    return 0


def _source_line(panel: dict, first_q: str, last_q: str) -> str:
    c = Counter(df["source"].iloc[0] if "source" in df else "?" for df in panel.values())
    provs = ", ".join(f"{k} {v:,}" for k, v in c.most_common())
    return (
        f"REAL: SEC Insider Transactions Data Sets {first_q} to {last_q}; "
        f"daily prices for {len(panel):,} tickers ({provs}); USD/KRW from FRED DEXKOUS"
    )


def cmd_backtest(args) -> int:
    cfg, p = _cfg_paths(args)
    tx = sec.load_transactions(p.sec)
    qs = sorted(f.stem for f in p.sec.glob("*.parquet"))
    pop, _ = pipeline.prepare_events(tx, cfg)
    bench_t = cfg["benchmark"]["ticker"]
    panel = prices.load_panel(set(pop["ticker"]) | {bench_t}, p.prices)
    if bench_t not in panel:
        print(f"benchmark {bench_t} prices missing; run fetch-prices", file=sys.stderr)
        return 1
    bench = panel.pop(bench_t)
    fx = prices.load_fx(cfg["benchmark"]["fx_series"], p.prices)
    res = pipeline.run(tx, panel, bench, fx, cfg, _source_line(panel, qs[0], qs[-1]))
    pipeline.save(res, p.results)
    report.render(p.results, p.reports, p.root / "README.md")
    print(report.headline(res))
    return 0


def cmd_report(args) -> int:
    _, p = _cfg_paths(args)
    report.render(p.results, p.reports, p.root / "README.md")
    print(f"wrote {p.reports / 'REPORT.md'}")
    return 0


def cmd_demo(args) -> int:
    from .synthetic import make_world

    cfg, p = _cfg_paths(args)
    w = make_world(seed=args.seed, drift_daily=args.drift)
    res = pipeline.run(
        w["tx"],
        w["panel"],
        w["bench"],
        w["fx"],
        cfg,
        f"SYNTHETIC (seed {args.seed}, planted drift {args.drift}/day)",
    )
    out = p.reports / "demo"
    pipeline.save(res, out / "results")
    report.render(out / "results", out)
    print(report.headline(res))
    return 0


def _price_lookup(p, cfg):
    def lookup(ticker):
        cached = prices.load_panel([ticker], p.prices).get(ticker)
        if cached is None or cached.index[-1] < pd.Timestamp.today() - pd.Timedelta(days=5):
            prices.update_cache(
                [ticker],
                p.prices,
                cfg["prices"]["providers"],
                "2020-01-01",
                refresh=True,
                pause=0,
                log=lambda *a: None,
            )
            cached = prices.load_panel([ticker], p.prices).get(ticker)
        if cached is None:
            return None, ""
        return cached["adj_close"], str(cached["source"].iloc[0])

    return lookup


def cmd_ledger(args) -> int:
    cfg, p = _cfg_paths(args)
    led, res = p.ledger / "ledger.csv", p.ledger / "resolutions.csv"
    if args.action == "add":
        row = L.append_claim(
            led,
            author=args.author,
            ticker=args.ticker.upper(),
            claim=args.claim,
            direction=args.direction,
            horizon_days=args.horizon,
            probability=args.probability,
            benchmark=args.benchmark,
            start_date=args.start,
            basis=args.basis,
            filing_age_days=args.filing_age,
            invalidation=args.invalidation,
        )
        print(f"appended {row['id']}")
    elif args.action == "score":
        try:
            fx = prices.fetch_fx(cfg["benchmark"]["fx_series"], p.prices)
        except Exception:  # offline: use the cached series
            fx = prices.load_fx(cfg["benchmark"]["fx_series"], p.prices)
        new = L.resolve(led, res, _price_lookup(p, cfg), fx)
        print(f"resolved {len(new)} claim(s)")
        card = L.scorecard(led, res)
        report.render_scorecard(card, p.reports / "SCORECARD.md")
        print(json.dumps({k: v for k, v in card.items() if k != "calibration"}, indent=1))
    elif args.action == "check":
        for f in (led, res):
            print(L.check_append_only(f, args.base, p.root))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="insiderlab")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data-check", help="check that SEC, FRED, Stooq and Yahoo are reachable")
    sub.add_parser("price-check", help="fetch a few known tickers and check splits")
    s = sub.add_parser("fetch-sec", help="download and normalise the SEC data sets")
    s.add_argument("--first")
    s.add_argument("--last")
    s = sub.add_parser("fetch-prices", help="prices for every event ticker, SPY and USD/KRW")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--retry-missing", dest="retry_missing", action="store_true")
    s.add_argument("--limit", type=int, default=0)
    sub.add_parser("backtest", help="run the pre-registered backtest and write the report")
    sub.add_parser("report", help="re-render REPORT.md and README from results")
    s = sub.add_parser("demo", help="full pipeline on synthetic data, no network")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--drift", type=float, default=0.0004)
    s = sub.add_parser("ledger", help="prediction ledger: add, score, check")
    s.add_argument("action", choices=["add", "score", "check"])
    s.add_argument("--author", default="saha")
    s.add_argument("--ticker", default="")
    s.add_argument("--claim", default="")
    s.add_argument("--direction", default="+1")
    s.add_argument("--horizon", type=int, default=91)
    s.add_argument("--probability", type=float, default=0.5)
    s.add_argument("--benchmark", default="SPY")
    s.add_argument("--start", default=None)
    s.add_argument("--basis", default="")
    s.add_argument("--filing-age", dest="filing_age", default="")
    s.add_argument("--invalidation", default="")
    s.add_argument("--base", default="HEAD~1")
    args = ap.parse_args(argv)
    handlers = {
        "data-check": cmd_data_check,
        "price-check": cmd_price_check,
        "fetch-sec": cmd_fetch_sec,
        "fetch-prices": cmd_fetch_prices,
        "backtest": cmd_backtest,
        "report": cmd_report,
        "demo": cmd_demo,
        "ledger": cmd_ledger,
    }
    started = datetime.now(UTC)
    code = handlers[args.cmd](args)
    print(f"[{args.cmd}] done in {(datetime.now(UTC) - started).total_seconds():.0f}s")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
