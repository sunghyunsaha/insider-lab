"""Append-only prediction ledger and its scoring.

Two CSV files, both append-only (CI rejects any commit that edits or deletes a past row):

* ``ledger/ledger.csv``       one row per claim, written when the claim is made.
* ``ledger/resolutions.csv``  one row per claim once its horizon has passed.

A claim is a probability that ``ticker`` beats (direction +1) or trails (direction -1)
the benchmark in KRW over ``horizon_days`` calendar days from ``start_date``. Resolutions
never overwrite claims; the scorecard joins the two files.
"""

from __future__ import annotations

import csv
import io
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

LEDGER_FIELDS = [
    "id",  # L-YYYYMMDD-NNN, unique
    "created_utc",  # when the row was written
    "author",  # system | saha
    "ticker",  # US ticker as on the exchange
    "claim",  # one sentence in plain words
    "direction",  # +1 beats the benchmark, -1 trails it
    "horizon_days",  # calendar days
    "probability",  # stated probability that the claim comes true, 0-1
    "benchmark",  # SPY (proxy for the TIGER S&P 500 core, both measured in KRW)
    "start_date",  # first date of the measurement window (YYYY-MM-DD)
    "basis",  # hypothesis or evidence behind it, e.g. "H3 cluster, 4 insiders"
    "filing_age_days",  # age of the newest filing behind the claim when it was made
    "invalidation",  # what would show the claim is wrong
]
RESOLUTION_FIELDS = [
    "id",
    "resolved_utc",
    "end_date",
    "ticker_return_krw",
    "benchmark_return_krw",
    "excess_krw",
    "outcome",
    "price_source",
]


def _ensure(path: Path, fields: list[str]) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh, lineterminator="\n").writerow(fields)


def read(path: Path, fields: list[str]) -> pd.DataFrame:
    _ensure(path, fields)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def validate_claim(row: dict, existing_ids: set[str]) -> list[str]:
    errors = []
    for f in LEDGER_FIELDS:
        if f not in row or str(row[f]).strip() == "":
            if f not in ("filing_age_days",):
                errors.append(f"missing {f}")
    if row.get("id") in existing_ids:
        errors.append(f"duplicate id {row.get('id')}")
    try:
        p = float(row["probability"])
        if not 0.0 < p < 1.0:
            errors.append("probability must be strictly between 0 and 1")
    except (KeyError, ValueError):
        errors.append("probability is not a number")
    if str(row.get("direction")) not in ("1", "+1", "-1"):
        errors.append("direction must be +1 or -1")
    try:
        if int(row["horizon_days"]) <= 0:
            errors.append("horizon_days must be positive")
    except (KeyError, ValueError):
        errors.append("horizon_days is not an integer")
    try:
        date.fromisoformat(str(row["start_date"]))
    except (KeyError, ValueError):
        errors.append("start_date must be YYYY-MM-DD")
    return errors


def next_id(existing: pd.DataFrame, today: date) -> str:
    prefix = f"L-{today:%Y%m%d}-"
    n = sum(1 for i in existing.get("id", []) if str(i).startswith(prefix))
    return f"{prefix}{n + 1:03d}"


def append_claim(path: Path, **kwargs) -> dict:
    df = read(path, LEDGER_FIELDS)
    today = datetime.now(UTC).date()
    row = {f: "" for f in LEDGER_FIELDS}
    row.update({k: str(v) for k, v in kwargs.items() if v is not None})
    row.setdefault("benchmark", "SPY")
    row["benchmark"] = row["benchmark"] or "SPY"
    row["id"] = row["id"] or next_id(df, today)
    row["created_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    row["start_date"] = row["start_date"] or today.isoformat()
    if row["direction"] == "1":
        row["direction"] = "+1"
    errors = validate_claim(row, set(df["id"]))
    if errors:
        raise ValueError("; ".join(errors))
    with open(path, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerow([row[f] for f in LEDGER_FIELDS])
    return row


def due_claims(ledger: pd.DataFrame, resolutions: pd.DataFrame, today: date) -> pd.DataFrame:
    done = set(resolutions["id"])
    out = ledger[~ledger["id"].isin(done)].copy()
    if out.empty:
        return out
    end = pd.to_datetime(out["start_date"]) + pd.to_timedelta(
        out["horizon_days"].astype(int), unit="D"
    )
    out["end_date"] = end.dt.date
    return out[out["end_date"] <= today]


def period_return(px: pd.Series, start: date, end: date) -> float:
    """Return from the last close on or before ``start`` to the last close on or before ``end``."""
    px = px.sort_index()
    a = px[px.index <= pd.Timestamp(start)]
    b = px[px.index <= pd.Timestamp(end)]
    if a.empty or b.empty:
        return float("nan")
    return float(b.iloc[-1] / a.iloc[-1] - 1)


def resolve(
    ledger_path: Path, res_path: Path, price_lookup, fx: pd.Series, today: date | None = None
) -> list[dict]:
    """Append a resolution for every claim whose horizon has passed.

    ``price_lookup(ticker) -> (adjusted close Series, source name)``.
    """
    today = today or datetime.now(UTC).date()
    led = read(ledger_path, LEDGER_FIELDS)
    res = read(res_path, RESOLUTION_FIELDS)
    rows = []
    for _, c in due_claims(led, res, today).iterrows():
        start, end = date.fromisoformat(c["start_date"]), c["end_date"]
        px, src = price_lookup(c["ticker"])
        bx, _ = price_lookup(c["benchmark"])
        if px is None or bx is None:
            continue  # stays unresolved; the scorecard lists it
        fx_r = period_return(fx, start, end)
        r_t = (1 + period_return(px, start, end)) * (1 + fx_r) - 1
        r_b = (1 + period_return(bx, start, end)) * (1 + fx_r) - 1
        if not (np.isfinite(r_t) and np.isfinite(r_b)):
            continue
        excess = r_t - r_b
        sign = 1 if c["direction"] in ("+1", "1") else -1
        rows.append(
            {
                "id": c["id"],
                "resolved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date": end.isoformat(),
                "ticker_return_krw": f"{r_t:.6f}",
                "benchmark_return_krw": f"{r_b:.6f}",
                "excess_krw": f"{excess:.6f}",
                "outcome": "1" if sign * excess > 0 else "0",
                "price_source": src,
            }
        )
    with open(res_path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        for r in rows:
            w.writerow([r[f] for f in RESOLUTION_FIELDS])
    return rows


def scorecard(ledger_path: Path, res_path: Path, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    led = read(ledger_path, LEDGER_FIELDS)
    res = read(res_path, RESOLUTION_FIELDS)
    j = led.merge(res, on="id", how="inner")
    out = {
        "claims": len(led),
        "resolved": len(j),
        "open": len(led) - len(j),
        "overdue": len(due_claims(led, res, today)),
    }
    if len(j):
        p = j["probability"].astype(float).to_numpy()
        y = j["outcome"].astype(int).to_numpy()
        ex = j["excess_krw"].astype(float).to_numpy()
        sign = np.where(j["direction"].isin(["+1", "1"]), 1, -1)
        out.update(
            {
                "hit_rate": float(y.mean()),
                "mean_stated_probability": float(p.mean()),
                "brier": float(np.mean((p - y) ** 2)),
                "brier_if_always_50pct": 0.25,
                "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
                "mean_signed_excess_krw": float(np.mean(sign * ex)),
            }
        )
        bins = pd.cut(p, [0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0], include_lowest=True)
        cal = (
            pd.DataFrame({"bin": bins, "p": p, "y": y})
            .groupby("bin", observed=True)
            .agg(n=("y", "size"), stated=("p", "mean"), realised=("y", "mean"))
        )
        out["calibration"] = cal.reset_index().astype({"bin": str}).to_dict(orient="records")
    return out


def check_append_only(path: Path, base_ref: str = "HEAD~1", repo: Path | None = None) -> str:
    """Raise if ``path`` at ``base_ref`` is not a prefix of the working-tree file."""
    repo = repo or path.parent.parent
    rel = path.resolve().relative_to(repo.resolve()).as_posix()
    try:
        old = subprocess.run(
            ["git", "show", f"{base_ref}:{rel}"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return f"{rel}: no earlier version at {base_ref}, nothing to compare"
    new = path.read_text(encoding="utf-8")
    old_rows = list(csv.reader(io.StringIO(old)))
    new_rows = list(csv.reader(io.StringIO(new)))
    if new_rows[: len(old_rows)] != old_rows:
        raise SystemExit(f"{rel}: an existing row was edited or deleted (append-only file)")
    return f"{rel}: ok, {len(new_rows) - len(old_rows)} row(s) appended"


def default_horizon_end(start: date, days: int) -> date:
    return start + timedelta(days=days)
