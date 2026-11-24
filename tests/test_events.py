import pandas as pd

from insiderlab import events as E


def _tx(rows):
    base = {
        "form": "4",
        "security_title": "Common Stock",
        "acq_disp": "A",
        "equity_swap": False,
        "plan_10b5_1": False,
        "issuer_name": "Acme Corp",
        "owner_title": "",
        "n_owners": 1,
        "is_officer": True,
        "is_director": False,
        "is_ten_pct": False,
        "direct": "D",
        "owner_name": "x",
    }
    out = []
    for i, r in enumerate(rows):
        d = {**base, **r}
        d.setdefault("accession", f"A{i}")
        d.setdefault("trans_sk", "1")
        d.setdefault("filing_date", pd.Timestamp(d["trans_date"]) + pd.Timedelta(days=2))
        d["trans_date"] = pd.Timestamp(d["trans_date"])
        d.setdefault("code", "P")
        d.setdefault("shares", 1000.0)
        d.setdefault("price", 10.0)
        d.setdefault("owned_after", 5000.0)
        d.setdefault("issuer_cik", "1")
        d.setdefault("ticker", "ACME")
        out.append(d)
    return pd.DataFrame(out)


def test_routine_opportunistic_unclassified():
    rows = []
    # insider R trades every March 2017-2019, then buys in March 2020 -> routine
    for y in (2017, 2018, 2019, 2020):
        rows.append({"owner_cik": "R", "trans_date": f"{y}-03-10"})
    # insider O trades each year but in different months, buys in June 2020 -> opportunistic
    for y, m in ((2017, 1), (2018, 5), (2019, 9), (2020, 6)):
        rows.append({"owner_cik": "O", "trans_date": f"{y}-{m:02d}-10"})
    # insider U has only two prior years -> unclassified
    for y in (2018, 2019, 2020):
        rows.append({"owner_cik": "U", "trans_date": f"{y}-03-10"})
    ev = E.purchase_events(_tx(rows))
    last = ev[ev["trans_date"].dt.year == 2020].set_index("owner_cik")["trader_class"]
    assert last["R"] == "routine"
    assert last["O"] == "opportunistic"
    assert last["U"] == "unclassified"


def test_sales_count_as_history_but_are_not_events():
    rows = [
        {"owner_cik": "S", "trans_date": f"{y}-04-01", "code": "S", "acq_disp": "D"}
        for y in (2017, 2018, 2019)
    ]
    rows.append({"owner_cik": "S", "trans_date": "2020-04-02"})
    ev = E.purchase_events(_tx(rows))
    assert len(ev) == 1 and ev["trader_class"].iloc[0] == "routine"


def test_cluster_uses_only_past_filings():
    rows = [
        {"owner_cik": "A", "trans_date": "2021-05-01"},
        {"owner_cik": "B", "trans_date": "2021-05-10"},
        {"owner_cik": "C", "trans_date": "2021-05-20"},
        {"owner_cik": "D", "trans_date": "2021-08-01"},  # outside the 30-day window
    ]
    ev = E.purchase_events(_tx(rows)).set_index("owner_cik")
    assert ev.loc["A", "cluster_n"] == 1  # later filings are not known yet
    assert ev.loc["B", "cluster_n"] == 2
    assert ev.loc["C", "cluster_n"] == 3
    assert ev.loc["D", "cluster_n"] == 1


def test_lots_aggregate_and_size():
    rows = [
        {
            "owner_cik": "A",
            "trans_date": "2021-05-01",
            "accession": "X",
            "trans_sk": "1",
            "shares": 100.0,
            "price": 10.0,
            "owned_after": 1100.0,
        },
        {
            "owner_cik": "A",
            "trans_date": "2021-05-02",
            "accession": "X",
            "trans_sk": "2",
            "shares": 100.0,
            "price": 12.0,
            "owned_after": 1200.0,
        },
    ]
    ev = E.purchase_events(_tx(rows))
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["shares"] == 200 and abs(e["price"] - 11.0) < 1e-9
    assert abs(e["frac_increase"] - 200 / 1000) < 1e-9


def test_population_filters():
    cfg = {
        "universe": {
            "officer_or_director": True,
            "min_price": 5.0,
            "min_value_usd": 25000,
            "exclude_name_regex": r"\bFUND\b|ACQUISITION CORP",
        }
    }
    rows = [
        {"owner_cik": "A", "trans_date": "2021-05-01", "shares": 5000.0, "price": 10.0},
        {"owner_cik": "B", "trans_date": "2021-05-01", "shares": 100.0, "price": 10.0},  # small
        {"owner_cik": "C", "trans_date": "2021-05-01", "shares": 9000.0, "price": 3.0},  # cheap
        {
            "owner_cik": "D",
            "trans_date": "2021-05-01",
            "shares": 5000.0,
            "price": 10.0,
            "issuer_name": "Big Income Fund",
            "issuer_cik": "2",
            "ticker": "BIF",
        },
        {
            "owner_cik": "E",
            "trans_date": "2021-05-01",
            "shares": 5000.0,
            "price": 10.0,
            "is_officer": False,
            "is_ten_pct": True,
        },
        {
            "owner_cik": "F",
            "trans_date": "2021-05-01",
            "shares": 5000.0,
            "price": 10.0,
            "plan_10b5_1": True,
        },
    ]
    pop, steps = E.apply_population(E.purchase_events(_tx(rows)), cfg)
    assert list(pop["owner_cik"]) == ["A"]
    assert steps["purchase_filings"] == 6
