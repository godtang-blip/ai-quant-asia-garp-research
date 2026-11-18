"""Research-only cross-sectional scoring. Not a trading signal or a company methodology."""
from __future__ import annotations
import math
import pandas as pd
import numpy as np

# Analyst-designed exploratory weights. These are NOT Redpoint Partners' proprietary rules.
METRICS = {
    "revenue_growth": (0.20, True),
    "earnings_growth": (0.15, True),
    "operating_margin": (0.15, True),
    "roe": (0.10, True),
    "fcf_yield": (0.15, True),
    "forward_pe": (0.15, False),
    "price_to_sales": (0.10, False),
}


def valid_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def rate_peer_universe(data: pd.DataFrame) -> pd.DataFrame:
    """Peer-relative exploratory scores; missing peer data cannot become PASS."""
    needed = {"ticker", "peer_group", *METRICS}
    missing = sorted(needed - set(data.columns))
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    d = data.copy()
    if d["ticker"].duplicated().any():
        raise ValueError("Universe has duplicate tickers")
    d["completeness"] = d[list(METRICS)].notna().sum(axis=1)
    d["peer_n"] = d.groupby("peer_group")["ticker"].transform("size")
    weighted = np.zeros(len(d), dtype=float)
    covered_weights = np.zeros(len(d), dtype=float)
    peer_sample_counts = {}
    for metric, (weight, prefer_high) in METRICS.items():
        values = pd.to_numeric(d[metric], errors="coerce")
        # Negative/zero PE and P/S ratios do not mean they are cheap.
        if metric in ("forward_pe", "price_to_sales"):
            values = values.where(values > 0)
        if metric in ("roe", "operating_margin"):
            values = values.where(values.between(-1.5, 1.5))
        if metric in ("revenue_growth", "earnings_growth"):
            values = values.where(values.between(-1.5, 5))
        if metric == "fcf_yield":
            values = values.where(values.between(-2, 2))
        d[metric] = values
        counts = values.groupby(d["peer_group"]).transform("count")
        ranks = values.groupby(d["peer_group"]).rank(pct=True, ascending=prefer_high)
        # pandas ascending=True means largest value highest percentile.
        scores = ranks  # ascending=True rewards higher; ascending=False rewards lower.
        scores = scores.where(counts >= 3)  # two-company peer group is not a useful ranking
        usable = scores.notna().to_numpy()
        weighted += np.where(usable, scores.fillna(0).to_numpy(), 0) * weight
        covered_weights += usable * weight
        peer_sample_counts[metric] = counts
    d["completeness"] = d[list(METRICS)].notna().sum(axis=1)
    d["coverage_weight"] = covered_weights
    d["exploratory_score_100"] = np.where(covered_weights > 0, 100 * weighted, np.nan)
    d["rankable"] = (d["completeness"] >= 5) & (d["peer_n"] >= 3) & (covered_weights >= 0.65)
    d.loc[~d["rankable"], "exploratory_score_100"] = np.nan
    d["screen_status"] = np.where(d["rankable"], "RESEARCH_CANDIDATE_ONLY", "REVIEW_DATA_OR_PEERS")
    return d.sort_values(["rankable", "exploratory_score_100", "ticker"], ascending=[False, False, True], na_position="last").reset_index(drop=True)
