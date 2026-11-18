"""Independent, exploratory peer-scoring; NOT a verified GARP valuation."""
from __future__ import annotations
import pandas as pd
import numpy as np

# Conceptual metrics; weights are arbitrary research hypotheses, NOT firm's rules.
METRICS = {
    "revenue_growth": (0.20, True),
    "earnings_growth": (0.15, True),
    "operating_margin": (0.15, True),
    "roe": (0.10, True),
    "fcf_yield": (0.15, True),
    "forward_pe": (0.15, False),
    "price_to_sales": (0.10, False),
}
BOUNDS = {
    "revenue_growth": (-1.5, 5.0),
    "earnings_growth": (-1.5, 5.0),
    "operating_margin": (-1.5, 1.5),
    "roe": (-1.5, 1.5),
    "fcf_yield": (-2.0, 2.0),
    "forward_pe": (0.0, 10000),
    "price_to_sales": (0.0, 10000),
}


def valid_number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return np.nan
    return n if np.isfinite(n) else np.nan


def _warning(row):
    """Heuristic triage only. Flags can be valid real observations."""
    flags = []
    pe = valid_number(row.get('forward_pe'))
    ps = valid_number(row.get('price_to_sales'))
    rg = valid_number(row.get('revenue_growth'))
    eg = valid_number(row.get('earnings_growth'))
    if np.isfinite(pe) and (pe < 5 or pe > 100):
        flags.append('EXTREME_FORWARD_PE_VERIFY_FILINGS')
    if np.isfinite(ps) and ps > 30:
        flags.append('EXTREME_PS_VERIFY_PEERS')
    if np.isfinite(rg) and (rg > 1 or rg < -0.60):
        flags.append('UNUSUAL_REVENUE_GROWTH_VERIFY_PERIOD')
    if np.isfinite(eg) and (eg > 2 or eg < -0.80):
        flags.append('UNUSUAL_EARNINGS_GROWTH_VERIFY_BASE')
    price = valid_number(row.get('current_price'))
    feps = valid_number(row.get('forward_eps'))
    if np.isfinite(price) and np.isfinite(feps) and price > 0 and feps > 0 and np.isfinite(pe) and pe > 0:
        derived = price / feps
        if abs(derived - pe) / pe > 0.20:
            flags.append('PE_EPS_PRICE_INCONSISTENCY')
    if str(row.get('info_warning', '')).strip() not in ('', 'nan', 'None'):
        flags.append('PROVIDER_CURRENCY_OR_FIELD_WARNING')
    return '|'.join(flags)


def rate_peer_universe(data: pd.DataFrame) -> pd.DataFrame:
    required = {'ticker', 'peer_group', *METRICS}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError('Missing required columns: '+', '.join(missing))
    d = data.copy().reset_index(drop=True)
    if d['ticker'].duplicated().any():
        raise ValueError('Universe has duplicate tickers')
    for metric in METRICS:
        vals = pd.to_numeric(d[metric], errors='coerce').replace([np.inf, -np.inf], np.nan)
        low, high = BOUNDS[metric]
        if metric in ('forward_pe', 'price_to_sales'):
            vals = vals.where(vals > 0)
        vals = vals.where(vals.between(low, high))
        d[metric] = vals
    d['completeness'] = d[list(METRICS)].notna().sum(axis=1)
    d['peer_n'] = d.groupby('peer_group')['ticker'].transform('size')
    weighted = np.zeros(len(d), dtype=float)
    covered = np.zeros(len(d), dtype=float)
    for metric, (weight, prefer_high) in METRICS.items():
        values = d[metric]
        peer_observations = values.groupby(d['peer_group']).transform('count')
        scores = values.groupby(d['peer_group']).rank(pct=True, ascending=prefer_high)
        scores = scores.where(peer_observations >= 3)
        usable = scores.notna().to_numpy()
        weighted += np.where(usable, scores.fillna(0).to_numpy(), 0) * weight
        covered += usable * weight
    d['coverage_weight'] = np.round(covered, 6)
    d['data_quality_flags'] = d.apply(_warning, axis=1)
    d['rankable'] = (d['completeness'] >= 5) & (d['peer_n'] >= 3) & (d['coverage_weight'] >= 0.65)
    # Normalize by ACTUALLY available metric weight; disclose coverage separately.
    d['exploratory_score_100'] = np.where(d['rankable'], 100 * weighted / np.maximum(covered, 1e-12), np.nan)
    # A numerical score is NOT a buy signal; flagged values must not enter the shortlist.
    d['shortlist_eligible'] = d['rankable'] & d['data_quality_flags'].eq('') & d.get('fetch_error', pd.Series('', index=d.index)).fillna('').eq('')
    d['screen_status'] = np.select(
        [~d['rankable'], d['data_quality_flags'].ne('')],
        ['REVIEW_DATA_OR_PEERS', 'REVIEW_SUSPECT_METRICS'],
        default='UNVERIFIED_RESEARCH_CANDIDATE',
    )
    d['source_verification'] = 'VENDOR_SNAPSHOT_NOT_VERIFIED_AGAINST_FILINGS'
    d = d.sort_values(['shortlist_eligible', 'rankable', 'exploratory_score_100', 'ticker'],
                      ascending=[False, False, False, True], na_position='last')
    return d.reset_index(drop=True)


def diversified_shortlist(ranked: pd.DataFrame, max_items: int = 10, max_per_group: int = 2) -> pd.DataFrame:
    """Take top member from each peer group before a second pass."""
    eligible = ranked[ranked['shortlist_eligible']].sort_values('exploratory_score_100', ascending=False)
    picked = []
    for round_no in range(1, max_per_group + 1):
        for _, r in eligible.iterrows():
            if len(picked) >= max_items: break
            group = r['peer_group']
            count = sum(q['peer_group'] == group for q in picked)
            if count == round_no-1 and not any(q['ticker'] == r['ticker'] for q in picked):
                picked.append(r)
        if len(picked) >= max_items: break
    return pd.DataFrame(picked, columns=ranked.columns).reset_index(drop=True)
