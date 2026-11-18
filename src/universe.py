"""Balanced CURATED-universe sampling, not whole-market discovery."""
from __future__ import annotations
import pandas as pd

# Analyst-controlled exploration order. Not based on results or the target firm's rules.
GROUP_ORDER = [
    "platforms", "industrial_electrification", "healthcare_biopharma",
    "gaming_media", "consumer_brands", "chip_equipment", "automakers",
    "chip_manufacturing", "chip_components",
]


def balanced_sample(universe: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Pick >=3 from each selected peer group where possible.

    With 12 slots: 4 groups x 3; with 24: 8 x 3.
    Max 0 means the entire curated list. Ensures partial runs aren't first-row-biased.
    """
    if limit < 0:
        raise ValueError("max_symbols cannot be negative")
    if limit == 0 or limit >= len(universe):
        return universe.copy().reset_index(drop=True)
    groups = list(universe['peer_group'].drop_duplicates())
    ordered = [g for g in GROUP_ORDER if g in groups] + sorted(set(groups) - set(GROUP_ORDER))
    peers = {g: universe[universe['peer_group'] == g].copy() for g in ordered}
    eligible = [g for g in ordered if len(peers[g]) >= 3]
    if limit < 3 or not eligible:
        return universe.head(limit).reset_index(drop=True)
    group_count = min(len(eligible), limit // 3)
    chosen = eligible[:group_count]
    allocated = {g: 3 for g in chosen}
    remaining = limit - 3 * group_count
    while remaining:
        advanced = False
        for group in chosen:
            if remaining <= 0:
                break
            if allocated[group] < len(peers[group]):
                allocated[group] += 1
                remaining -= 1
                advanced = True
        if not advanced:
            break
    selected = pd.concat([peers[g].head(allocated[g]) for g in chosen], ignore_index=True)
    return selected
