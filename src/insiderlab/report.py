"""Render reports/REPORT.md, the README headline and a figure from the results JSON.

Every number in those files is written here from ``reports/results/backtest.json``;
none is typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

START, END = "<!-- results:start -->", "<!-- results:end -->"


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f}%"


def headline(r: dict) -> str:
    hyp = {h["id"]: h for h in r["hypotheses"]}
    conf = [h for h in r["hypotheses"] if h["kind"] != "control"]
    supported = [h["id"] for h in conf if h["supported"]]
    d = r["diagnostics"]
    h1 = hyp["H1"]
    lines = [
        f"**Data:** {r['data_source']}. In-sample {r['sample']['start']} to "
        f"{r['sample']['end']}; 2024 onwards is held out and has not been looked at.",
        "",
        f"**Headline.** {len(supported)} of {len(conf)} confirmatory hypotheses survive Holm "
        f"at 5% ({', '.join(supported) if supported else 'none'}). "
        f"Officer and director purchases (H1) earned {pct(h1['ann_effect'])} a year over SPY "
        f"after modelled costs (t = {h1['t_hac']:.2f}). "
        f"The best of {d['n_trials']} variants has an annualised information ratio of "
        f"{d['best_info_ratio_annual']:.2f} against {d['expected_max_info_ratio_annual']:.2f} "
        f"expected from luck alone: **deflated Sharpe ratio {d['dsr']:.2f}** (0.95 needed), "
        f"**probability of backtest overfitting {d['pbo']:.2f}**.",
    ]
    return "\n".join(lines)


def hypotheses_table(r: dict) -> str:
    rows = [
        "| Hypothesis | Events | Effect a year | t (HAC) | p Holm | Verdict |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for h in r["hypotheses"]:
        verdict = (
            ("control passes" if h["supported"] else "control FAILS")
            if h["kind"] == "control"
            else ("supported" if h["supported"] else "not supported")
        )
        holm = f"{h['p_holm']:.3f}" if "p_holm" in h else "n/a (control)"
        ev = " vs ".join(str(n) for n in h["n_events"])
        rows.append(
            f"| **{h['id']}** {h['text']} | {ev} | {pct(h['ann_effect'])} | "
            f"{h['t_hac']:.2f} | {holm} | {verdict} |"
        )
    return "\n".join(rows)


def alpha_table(r: dict) -> str:
    rows = [
        "| Hypothesis | Effect a year | Beta to SPY | CAPM alpha a year | t (alpha) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for h in r["hypotheses"]:
        if "ann_alpha_capm" in h:
            rows.append(
                f"| {h['id']} | {pct(h['ann_effect'])} | {h['beta_to_spy']:+.2f} | "
                f"{pct(h['ann_alpha_capm'])} | {h['t_alpha_capm']:.2f} |"
            )
    return "\n".join(rows)


def robustness_table(r: dict) -> str:
    df = pd.DataFrame(r["robustness"])
    piv = df.pivot_table(index="spec", columns="id", values="ann_effect", aggfunc="first")
    tv = df.pivot_table(index="spec", columns="id", values="t_hac", aggfunc="first")
    cols = list(piv.columns)
    out = ["| Specification | " + " | ".join(cols) + " |", "| --- |" + " --- |" * len(cols)]
    for spec in piv.index:
        cells = [f"{pct(piv.loc[spec, c])} ({tv.loc[spec, c]:.1f})" for c in cols]
        out.append(f"| {spec} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def subperiod_table(r: dict) -> str:
    df = pd.DataFrame(r["subperiods"])
    piv = df.pivot_table(index="period", columns="id", values="ann_effect", aggfunc="first")
    cols = list(piv.columns)
    out = ["| Period | " + " | ".join(cols) + " |", "| --- |" + " --- |" * len(cols)]
    for p in piv.index:
        out.append(f"| {p} | " + " | ".join(pct(piv.loc[p, c]) for c in cols) + " |")
    return "\n".join(out)


def funnel_table(r: dict) -> str:
    out = ["| Step | Events left |", "| --- | --- |"]
    out += [f"| {k.replace('_', ' ')} | {v:,} |" for k, v in r["funnel"].items()]
    return "\n".join(out)


def figure(curves: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(curves)
    df["dates"] = pd.to_datetime(df["dates"])
    fig, ax = plt.subplots(figsize=(9, 4.2))
    styles = {
        "all": ("#222222", 2.0),
        "opportunistic": ("#1f77b4", 1.3),
        "routine": ("#aaaaaa", 1.3),
        "cluster": ("#d62728", 1.3),
        "single": ("#ff9896", 1.0),
    }
    for name, (color, lw) in styles.items():
        if name in df:
            ax.plot(df["dates"], df[name] * 100, color=color, lw=lw, label=name)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("cumulative excess over SPY, % (sum of daily)")
    ax.set_title("Primary specification (lag 1, 126-day hold, 1x costs), in-sample")
    ax.legend(frameon=False, ncol=5, fontsize=8, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def render(results_dir: Path, reports_dir: Path, readme: Path | None = None) -> str:
    r = json.loads((results_dir / "backtest.json").read_text())
    curves = pd.read_csv(results_dir / "cumulative_excess.csv").to_dict(orient="list")
    figure(curves, reports_dir / "figures" / "cumulative_excess.png")
    d, k = r["diagnostics"], r["krw"]
    body = f"""# insider-lab backtest report

Generated {r["generated_utc"]} from `reports/results/backtest.json`. Hypotheses registered
{r["registered"]} (see HYPOTHESES.md). Everything below is research, not advice.

{headline(r)}

![Cumulative excess](figures/cumulative_excess.png)

## Pre-registered hypotheses (primary specification)

Lag {r["primary_spec"]["lag"]} trading day after the filing date,
{r["primary_spec"]["horizon"]}-day hold, modelled costs (commission, FX, half-spread by liquidity). Effects are annualised
mean daily excess returns over SPY; "vs" rows are long-short differences between two legs.
Holm and Benjamini-Hochberg run over the five confirmatory hypotheses; H5 is a negative
control and passes when routine buyers show NO significant excess.

{hypotheses_table(r)}

## Beta check (robustness, not a pre-registered test)

Excess over SPY can come from market exposure rather than information. A leg tilted
towards small, volatile stocks has a beta different from 1; the CAPM alpha removes that
part. Size, value and momentum are not removed yet (LIMITATIONS.md, item 7).

{alpha_table(r)}

## Overfitting diagnostics (all {d["n_trials"]} leg x lag x horizon variants)

| Measure | Value |
| --- | --- |
| Best variant | `{d["best_column"]}` |
| Its annualised information ratio | {d["best_info_ratio_annual"]:.2f} |
| Expected best from {d["n_trials"]} skill-less variants | {d["expected_max_info_ratio_annual"]:.2f} |
| Deflated Sharpe ratio (raw trial count) | {d["dsr"]:.3f} |
| Effective independent trials (eigenvalue / average correlation) | {d["effective_trials_eigen"]:.1f} / {d["effective_trials_avg_corr"]:.1f} |
| Deflated Sharpe ratio (effective trials) | {d["dsr_effective_trials"]:.3f} |
| Probability of backtest overfitting (CSCV, {d["pbo_blocks"]} blocks) | {d["pbo"]:.3f} |
| Share of splits where the in-sample winner lost out of sample | {d["pbo_prob_oos_loss"]:.3f} |
| Variants significant at 5%: naive / Holm / BH | {d["survivors_5pct"]["naive"]} / {d["survivors_5pct"]["holm"]} / {d["survivors_5pct"]["bh"]} |

## Robustness (annualised effect, t-statistic in brackets)

Other specifications are counted as trials above; they cannot rescue a failed primary test.

{robustness_table(r)}

## Sub-periods (primary specification)

A hypothesis needs the same sign in at least three of the four periods (HYPOTHESES.md).

{subperiod_table(r)}

## In won: benchmark versus benchmark plus the H1 signal

Both legs are dollar assets, so USD/KRW ({k["usdkrw_start"]:.0f} to {k["usdkrw_end"]:.0f} over
the window) moves them together. Over {k["years"]:.1f} years SPY returned
{pct(k["benchmark_krw_cagr"])} a year in KRW and SPY plus the H1 excess
{pct(k["signal_krw_cagr"])} a year, before Korean tax (see docs/TAX.md).

## Data funnel

{funnel_table(r)}

## What this cannot tell you

See LIMITATIONS.md. The largest known bias: free price sources mostly lack delisted
companies, so events in firms that later failed are under-represented, which flatters
every leg. The holdout (2024 onwards) stays locked until DECISIONS.md records the decision
to open it.
"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "REPORT.md").write_text(body, encoding="utf-8")
    if readme and readme.exists():
        text = readme.read_text(encoding="utf-8")
        if START in text and END in text:
            a, b = text.index(START) + len(START), text.index(END)
            block = (
                "\n" + headline(r) + "\n\n" + hypotheses_table(r) + "\n\n"
                "Full report: [reports/REPORT.md](reports/REPORT.md)\n"
            )
            readme.write_text(text[:a] + block + text[b:], encoding="utf-8")
    return body


def render_scorecard(card: dict, path: Path) -> None:
    lines = [
        "# Prediction ledger scorecard",
        "",
        f"Claims {card['claims']}, resolved {card['resolved']}, open {card['open']}, "
        f"overdue (horizon passed, not yet resolved) {card['overdue']}.",
        "",
    ]
    if card.get("resolved"):
        lines += [
            "| Measure | Value |",
            "| --- | --- |",
            f"| Hit rate | {card['hit_rate']:.1%} |",
            f"| Mean stated probability | {card['mean_stated_probability']:.1%} |",
            f"| Brier score (0.25 = always saying 50%) | {card['brier']:.3f} |",
            f"| Log loss | {card['log_loss']:.3f} |",
            f"| Mean signed excess return in KRW | {pct(card['mean_signed_excess_krw'], 2)} |",
            "",
            "## Calibration",
            "",
            "| Stated probability | Claims | Mean stated | Realised |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {c['bin']} | {c['n']} | {c['stated']:.0%} | {c['realised']:.0%} |"
            for c in card["calibration"]
        ]
    else:
        lines.append("Nothing resolved yet: no claim has reached its horizon.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
