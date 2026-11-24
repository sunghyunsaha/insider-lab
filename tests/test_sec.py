import io
import zipfile

import pandas as pd

from insiderlab import sec


def _tables():
    sub = pd.DataFrame(
        {
            "ACCESSION_NUMBER": ["A1", "A2"],
            "FILING_DATE": ["15-MAR-2024", "02-JAN-2023"],
            "DOCUMENT_TYPE": ["4", "4"],
            "ISSUERCIK": ["0000012345", "0000099999"],
            "ISSUERNAME": ["Acme Corp", "Beta Inc"],
            "ISSUERTRADINGSYMBOL": ["acme", "BETA"],
            "AFF10B5ONE": ["0", "1"],
        }
    )
    own = pd.DataFrame(
        {
            "ACCESSION_NUMBER": ["A1", "A2", "A2"],
            "RPTOWNERCIK": ["0000000001", "0000000002", "0000000003"],
            "RPTOWNERNAME": ["Ann", "Bob", "Bob Trust"],
            "RPTOWNER_RELATIONSHIP": ["Director", "Officer", "TenPercentOwner"],
            "RPTOWNER_TITLE": ["", "CEO", ""],
        }
    )
    trn = pd.DataFrame(
        {
            "ACCESSION_NUMBER": ["A1", "A2"],
            "NONDERIV_TRANS_SK": ["1", "2"],
            "SECURITY_TITLE": ["Common Stock", "Common Stock"],
            "TRANS_DATE": ["13-MAR-2024", "29-DEC-2022"],
            "TRANS_CODE": ["P", "S"],
            "EQUITY_SWAP_INVOLVED": ["0", "0"],
            "TRANS_SHARES": ["1,000", "500"],
            "TRANS_PRICEPERSHARE": ["12.5", "40"],
            "TRANS_ACQUIRED_DISP_CD": ["A", "D"],
            "SHRS_OWND_FOLWNG_TRANS": ["11000", "0"],
            "DIRECT_INDIRECT_OWNERSHIP": ["D", "I"],
        }
    )
    return sub, own, trn


def test_quarters_and_latest():
    assert sec.quarters("2023q3", "2024q2") == ["2023q3", "2023q4", "2024q1", "2024q2"]
    assert sec.latest_possible_quarter(pd.Timestamp("2026-11-25")) == "2026q3"
    assert sec.latest_possible_quarter(pd.Timestamp("2026-02-01")) == "2025q4"


def test_normalise_tables():
    out = sec.normalise_tables(*_tables())
    a = out.set_index("accession")
    assert a.loc["A1", "filing_date"] == pd.Timestamp("2024-03-15")
    assert a.loc["A1", "trans_date"] == pd.Timestamp("2024-03-13")
    assert a.loc["A1", "shares"] == 1000 and a.loc["A1", "price"] == 12.5
    assert a.loc["A1", "ticker"] == "ACME" and a.loc["A1", "issuer_cik"] == "12345"
    assert bool(a.loc["A1", "is_director"]) and not bool(a.loc["A1", "is_officer"])
    assert a.loc["A2", "n_owners"] == 2  # joint filing
    assert bool(a.loc["A2", "is_officer"]) and bool(a.loc["A2", "is_ten_pct"])
    assert bool(a.loc["A2", "plan_10b5_1"]) and not bool(a.loc["A1", "plan_10b5_1"])


def test_normalise_quarter_from_zip(tmp_path):
    sub, own, trn = _tables()
    sub = sub.drop(columns="AFF10B5ONE")  # pre-2023 files have no 10b5-1 column
    path = tmp_path / "2020q1_form345.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, df in [("SUBMISSION", sub), ("REPORTINGOWNER", own), ("NONDERIV_TRANS", trn)]:
            buf = io.StringIO()
            df.to_csv(buf, sep="\t", index=False)
            zf.writestr(f"{name}.tsv", buf.getvalue())
    out = sec.normalise_quarter(path)
    assert len(out) == 2 and not out["plan_10b5_1"].any()


def test_parse_date_tolerates_iso():
    s = pd.Series(["15-MAR-2024", "2024-03-16", ""])
    out = sec.parse_date(s)
    assert out.iloc[0] == pd.Timestamp("2024-03-15")
    assert out.iloc[1] == pd.Timestamp("2024-03-16")
    assert pd.isna(out.iloc[2])
