"""Download and normalise the SEC Insider Transactions Data Sets (Forms 3, 4 and 5).

Source: https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
Format (insider_transactions_readme.pdf): one zip per quarter with tab-separated UTF-8
tables; dates are DD-MON-YYYY. We keep three tables:

* SUBMISSION      one row per filing: FILING_DATE, DOCUMENT_TYPE, issuer CIK/name/ticker,
                  and (2023 onwards) AFF10B5ONE, the Rule 10b5-1 checkbox.
* REPORTINGOWNER  one row per reporting person: relationship (OFFICER, DIRECTOR,
                  TENPERCENTOWNER, OTHER) and title.
* NONDERIV_TRANS  one row per non-derivative transaction: code, date, shares, price,
                  acquired/disposed, shares owned afterwards.

The signal date is FILING_DATE, never TRANS_DATE. The data sets carry the filing date
but not the acceptance time, so the backtest enters no earlier than the close of the
next trading day (``signal.lags``).
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

URL_PATTERNS = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip",
    # The SEC page lists 2026 Q2 and Q3 under a different folder.
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{q}_form345.zip",
)

SUBMISSION_COLS = [
    "ACCESSION_NUMBER",
    "FILING_DATE",
    "DOCUMENT_TYPE",
    "ISSUERCIK",
    "ISSUERNAME",
    "ISSUERTRADINGSYMBOL",
    "AFF10B5ONE",
]
OWNER_COLS = [
    "ACCESSION_NUMBER",
    "RPTOWNERCIK",
    "RPTOWNERNAME",
    "RPTOWNER_RELATIONSHIP",
    "RPTOWNER_TITLE",
]
TRANS_COLS = [
    "ACCESSION_NUMBER",
    "NONDERIV_TRANS_SK",
    "SECURITY_TITLE",
    "TRANS_DATE",
    "TRANS_CODE",
    "EQUITY_SWAP_INVOLVED",
    "TRANS_SHARES",
    "TRANS_PRICEPERSHARE",
    "TRANS_ACQUIRED_DISP_CD",
    "SHRS_OWND_FOLWNG_TRANS",
    "DIRECT_INDIRECT_OWNERSHIP",
]


def quarters(first: str, last: str) -> list[str]:
    """Inclusive list of quarter labels such as ``['2023q4', '2024q1']``."""
    y0, q0 = int(first[:4]), int(first[-1])
    y1, q1 = int(last[:4]), int(last[-1])
    out = []
    y, q = y0, q0
    while (y, q) <= (y1, q1):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def latest_possible_quarter(today: pd.Timestamp | None = None) -> str:
    """The last fully finished quarter; the SEC posts it some weeks later."""
    today = today or pd.Timestamp.today()
    q = (today.month - 1) // 3  # quarters finished this year
    if q == 0:
        return f"{today.year - 1}q4"
    return f"{today.year}q{q}"


def _user_agent(env_name: str) -> str:
    ua = os.environ.get(env_name, "").strip()
    if not ua or "@" not in ua:
        raise RuntimeError(
            f"Set {env_name} to something like 'insider-lab you@example.com'. "
            "The SEC rejects automated requests without a declared User-Agent."
        )
    return ua


def download_quarter(q: str, user_agent: str, dest: Path, pause: float = 0.2) -> Path:
    """Download one quarterly zip (cached). Returns the local path."""
    import requests

    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{q}_form345.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    last_error = None
    for pattern in URL_PATTERNS:
        url = pattern.format(q=q)
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=120)
            except requests.RequestException as exc:  # network trouble: retry
                last_error = f"{url}: {exc}"
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 200 and resp.content[:2] == b"PK":
                path.write_bytes(resp.content)
                time.sleep(pause)
                return path
            last_error = f"{url}: HTTP {resp.status_code}"
            if resp.status_code == 404:
                break
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not download {q}: {last_error}")


def _read_table(zf: zipfile.ZipFile, table: str, cols: list[str]) -> pd.DataFrame:
    names = [n for n in zf.namelist() if Path(n).stem.upper() == table]
    if not names:
        raise KeyError(f"{table} not found in archive; members: {zf.namelist()}")
    with zf.open(names[0]) as fh:
        raw = fh.read()
    df = pd.read_csv(
        io.BytesIO(raw),
        sep="\t",
        dtype=str,
        quoting=3,
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
        keep_default_na=False,
    )
    df.columns = [c.strip().upper() for c in df.columns]
    for c in cols:
        if c not in df.columns:
            df[c] = ""  # e.g. AFF10B5ONE before 2023
    return df[cols]


def parse_date(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    missing = out.isna() & s.astype(str).str.len().gt(0)
    if missing.any():  # tolerate a format change rather than silently dropping rows
        out.loc[missing] = pd.to_datetime(s[missing], errors="coerce")
    return out


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")


def normalise_quarter(zip_path: Path) -> pd.DataFrame:
    """One row per non-derivative transaction with filing and owner attributes."""
    with zipfile.ZipFile(zip_path) as zf:
        sub = _read_table(zf, "SUBMISSION", SUBMISSION_COLS)
        own = _read_table(zf, "REPORTINGOWNER", OWNER_COLS)
        trn = _read_table(zf, "NONDERIV_TRANS", TRANS_COLS)
    return normalise_tables(sub, own, trn)


def normalise_tables(sub: pd.DataFrame, own: pd.DataFrame, trn: pd.DataFrame) -> pd.DataFrame:
    rel = own.copy()
    rel["REL"] = rel["RPTOWNER_RELATIONSHIP"].str.upper()
    # A filing can list several reporting persons (joint filings). Keep the first as the
    # trader and record how many there were; flags are the union over all of them.
    agg = rel.groupby("ACCESSION_NUMBER", sort=False).agg(
        owner_cik=("RPTOWNERCIK", "first"),
        owner_name=("RPTOWNERNAME", "first"),
        owner_title=("RPTOWNER_TITLE", "first"),
        rel=("REL", lambda x: ",".join(x)),
        n_owners=("RPTOWNERCIK", "size"),
    )
    df = trn.merge(sub, on="ACCESSION_NUMBER", how="inner").merge(
        agg, left_on="ACCESSION_NUMBER", right_index=True, how="left"
    )
    out = pd.DataFrame(
        {
            "accession": df["ACCESSION_NUMBER"],
            "trans_sk": df["NONDERIV_TRANS_SK"],
            "filing_date": parse_date(df["FILING_DATE"]),
            "trans_date": parse_date(df["TRANS_DATE"]),
            "form": df["DOCUMENT_TYPE"].str.strip(),
            "issuer_cik": df["ISSUERCIK"].str.lstrip("0"),
            "issuer_name": df["ISSUERNAME"].str.strip(),
            "ticker": df["ISSUERTRADINGSYMBOL"].str.strip().str.upper(),
            "security_title": df["SECURITY_TITLE"].str.strip(),
            "code": df["TRANS_CODE"].str.strip().str.upper(),
            "acq_disp": df["TRANS_ACQUIRED_DISP_CD"].str.strip().str.upper(),
            "shares": _num(df["TRANS_SHARES"]),
            "price": _num(df["TRANS_PRICEPERSHARE"]),
            "owned_after": _num(df["SHRS_OWND_FOLWNG_TRANS"]),
            "direct": df["DIRECT_INDIRECT_OWNERSHIP"].str.strip().str.upper(),
            "equity_swap": df["EQUITY_SWAP_INVOLVED"].str.strip().isin(["1", "Y", "TRUE"]),
            "plan_10b5_1": df["AFF10B5ONE"].str.strip().str.upper().isin(["1", "Y", "TRUE"]),
            "owner_cik": df["owner_cik"].fillna("").str.lstrip("0"),
            "owner_name": df["owner_name"].fillna(""),
            "owner_title": df["owner_title"].fillna(""),
            "n_owners": df["n_owners"].fillna(0).astype(int),
        }
    )
    rel_s = df["rel"].fillna("")
    out["is_officer"] = rel_s.str.contains("OFFICER")
    out["is_director"] = rel_s.str.contains("DIRECTOR")
    out["is_ten_pct"] = rel_s.str.contains("TENPERCENT")
    return out


def build_tables(
    qs: Iterable[str],
    out_dir: Path,
    raw_dir: Path,
    user_agent: str | None = None,
    env_name: str = "SEC_USER_AGENT",
) -> dict[str, int]:
    """Download (if needed) and normalise each quarter to ``data/sec/<q>.parquet``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    ua = None
    for q in qs:
        target = out_dir / f"{q}.parquet"
        if target.exists():
            counts[q] = len(pd.read_parquet(target, columns=["accession"]))
            continue
        zip_path = raw_dir / f"{q}_form345.zip"
        if not zip_path.exists():
            ua = ua or user_agent or _user_agent(env_name)
            zip_path = download_quarter(q, ua, raw_dir)
        df = normalise_quarter(zip_path)
        df.to_parquet(target, index=False)
        counts[q] = len(df)
    return counts


def load_transactions(sec_dir: Path) -> pd.DataFrame:
    files = sorted(sec_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no SEC tables in {sec_dir}; run `insiderlab fetch-sec` first")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    # Amendments and re-postings can repeat a transaction across quarters.
    return df.drop_duplicates(["accession", "trans_sk"]).reset_index(drop=True)
