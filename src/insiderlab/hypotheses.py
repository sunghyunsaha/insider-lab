"""Machine-readable copy of the pre-registered hypotheses in HYPOTHESES.md.

Registered 2026-11-25, before any insider data was downloaded. Changing this file after
that date is a new trial and must be logged in DECISIONS.md.

Each hypothesis has ONE primary test on the primary specification (lag 1, 126-day hold,
1x costs, 0% delisting return, in-sample 2009-01-01 to 2023-12-31). The other
specifications are robustness checks and are counted as trials in the deflated Sharpe
ratio, but they do not rescue a failed primary test.
"""

from __future__ import annotations

REGISTERED = "2026-11-25"

PRIMARY_SPEC = {"lag": 1, "horizon": 126, "cost_multiplier": 1.0}

# kind: "long"  -> test mean(excess of leg) > 0
#       "diff"  -> test mean(excess of leg_a - excess of leg_b) > 0
#       "control" -> expected NOT to be significantly positive (negative control)
HYPOTHESES = [
    {
        "id": "H1",
        "kind": "long",
        "legs": ["all"],
        "text": "Open-market purchases by officers and directors beat the S&P 500 after costs.",
    },
    {
        "id": "H2",
        "kind": "diff",
        "legs": ["opportunistic", "routine"],
        "text": "Opportunistic buyers beat routine buyers.",
    },
    {
        "id": "H3",
        "kind": "diff",
        "legs": ["cluster", "single"],
        "text": "Cluster purchases (3+ insiders in 30 days) beat single-insider purchases.",
    },
    {
        "id": "H4",
        "kind": "diff",
        "legs": ["postdrop", "nodrop"],
        "text": "Purchases after a 20%+ drop over 63 trading days beat other purchases.",
    },
    {
        "id": "H5",
        "kind": "control",
        "legs": ["routine"],
        "text": "Negative control: routine buyers show no excess return over the S&P 500.",
    },
    {
        "id": "H6",
        "kind": "diff",
        "legs": ["large", "small"],
        "text": "Purchases that raise the insider's holding by 10%+ beat smaller ones.",
    },
]

# Holm and Benjamini-Hochberg run over these (the control is reported separately).
CONFIRMATORY = ["H1", "H2", "H3", "H4", "H6"]
