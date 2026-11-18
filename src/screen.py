"""Asia GARP exploratory screener. Research only: no order placement, no real-money trades."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from .ranking import METRICS, rate_peer_universe, valid_number

FIELD_MAP = {
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "operating_margin": "operatingMargins",
    "roe": "returnOnEquity",
    "forward_pe": "forwardPE",
    "price_to_sales": "priceToSalesTrailing12Months",
}


def pull_ticker(ticker: str) -> dict:
    import yfinance as yf
    info = yf.Ticker(ticker).get_info() or {}
    if not info or not isinstance(info, dict):
        raise RuntimeError("Data provider returned no fundamentals")
    result = {key: valid_number(info.get(original)) for key, original in FIELD_MAP.items()}
    fcf = valid_number(info.get("freeCashflow"))
    cap = valid_number(info.get("marketCap"))
    quote_cur = str(info.get("currency") or "")
    financial_cur = str(info.get("financialCurrency") or "")
    if (np.isfinite(fcf) and np.isfinite(cap) and cap > 0 and quote_cur and financial_cur and quote_cur == financial_cur):
        result["fcf_yield"] = fcf / cap
    else:
        result["fcf_yield"] = np.nan
    result["market_cap"] = cap
    result["currency"] = quote_cur
    result["financial_currency"] = financial_cur
    result["provider_name"] = info.get("longName") or info.get("shortName") or ""
    result["info_warning"] = "" if quote_cur and financial_cur and quote_cur == financial_cur else "Currency mismatch/missing: FCF yield omitted"
    return result


def markdown_report(ranked: pd.DataFrame, retrieved_at: str) -> str:
    qualified = ranked[ranked["rankable"]].head(10)
    out = [
        "# Independent Asia GARP research screener — EXPLORATORY ONLY",
        "", f"Retrieved at (UTC): {retrieved_at}", "",
        "**Independent portfolio research prototype; not affiliated with Redpoint Partners.**",
        "", "No buy recommendations, no portfolio allocation, no brokerage connectivity.",
        "Public-provider fundamental snapshots are NOT verified point-in-time. Historical backtesting or evidence of current undervaluation is NOT supported.",
        "Peer groups are approximate research categories and are not a substitute for company-specific comparable analysis.",
        "Scores are user-defined exploratory rankings, not a replication of any firm's investment methodology.",
        "", f"Universe: {len(ranked)} | Scored: {len(qualified)} in shortlist, {int(ranked['rankable'].sum())} rankable overall | Needs review: {int((~ranked['rankable']).sum())}",
        "", "## Research shortlist for HUMAN review",
        "", "| Ticker | Market | Peer group | Exploratory score/100 | Revenue growth | Forward PE | Data coverage |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for _, row in qualified.iterrows():
        def fmt(v, percent=False):
            if pd.isna(v): return "N/A"
            return (f"{v*100:.1f}%" if percent else f"{v:.1f}")
        out.append(f"| {row['ticker']} | {row.get('market','')} | {row['peer_group']} | {fmt(row['exploratory_score_100'])} | {fmt(row['revenue_growth'],True)} | {fmt(row['forward_pe'])} | {int(row['completeness'])}/7 |")
    if qualified.empty:
        out.append("| No valid candidate | — | — | — | — | — | — |")
    out += [
        "", "## Before writing an investment idea", "",
        "1. Verify revenue drivers, price realization, margins, cash conversion and investment needs from primary filings.",
        "2. Compare *comparable* companies and use at least two valuation approaches where suitable; document assumptions and ranges.",
        "3. Identify the market's likely disagreement and an actual, sourced re-rating catalyst; explain a bear case and invalidation trigger.",
        "4. Check disclosure publication dates, fiscal periods, corporate actions, ticker conventions and currency conversions manually.",
        "5. Discuss the idea as a hypothesis with the PM; this screener is an idea generator, not an investment conclusion.",
        "", "## Data failures and missing information",
    ]
    bad = ranked[(ranked.get("fetch_error", "") != "") | (~ranked["rankable"])]
    if len(bad):
        for _, row in bad.head(30).iterrows():
            out.append(f"- {row['ticker']}: {row.get('fetch_error','') or 'Insufficient fundamentals/peer sample'}")
    else:out.append("- No flagged rows; still verify vendor fundamentals against original filings.")
    return "\n".join(out) + "\n"


def run(universe_file: Path, outputs: Path, max_symbols: int, delay_seconds: float) -> None:
    universe = pd.read_csv(universe_file, dtype=str).fillna("")
    for col in ["ticker", "market", "peer_group", "company", "industry_thesis"]:
        if col not in universe.columns:
            raise ValueError(f"Universe needs column: {col}")
    if universe["ticker"].duplicated().any():
        raise ValueError("Duplicate ticker in universe")
    if not universe["ticker"].str.strip().all():
        raise ValueError("Blank ticker in universe")
    if max_symbols > 0: universe = universe.head(max_symbols)
    rows=[]
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for i, (_, u) in enumerate(universe.iterrows(), 1):
        sym = u["ticker"]
        print(f"[{i}/{len(universe)}] Research snapshot {sym}", flush=True)
        row = u.to_dict()
        row.update({m: np.nan for m in METRICS})
        row["retrieved_at_utc"] = retrieved_at
        row["fetch_error"] = ""
        try:
            row.update(pull_ticker(sym))
        except Exception as e:
            row["fetch_error"] = type(e).__name__ + ": " + str(e)[:160]
        rows.append(row)
        if delay_seconds and i < len(universe): time.sleep(delay_seconds)
    d = pd.DataFrame(rows)
    if not d["fetch_error"].eq("").any():
        raise RuntimeError("All provider requests failed; no fake or stale fallback. Check market data / rate limits.")
    scored = rate_peer_universe(d)
    outputs.mkdir(parents=True, exist_ok=True)
    scored.to_csv(outputs / "01_all_research_candidates.csv", index=False, encoding="utf-8-sig")
    scored[scored["rankable"]].head(10).to_csv(outputs / "02_research_shortlist.csv", index=False, encoding="utf-8-sig")
    (outputs / "03_research_report.md").write_text(markdown_report(scored, retrieved_at), encoding="utf-8")
    meta = {"retrieved_at_utc":retrieved_at,"universe_n":len(universe),"rankable_n":int(scored["rankable"].sum()),"data_errors_n":int((~scored["fetch_error"].eq("")).sum()),"paper_or_real_orders":"NONE","source":"yfinance exploratory"}
    (outputs / "04_run_metadata.json").write_text(json.dumps(meta, indent=2),encoding="utf-8")
    print(f"Research-only results in {outputs}; {meta['rankable_n']} rankable / {meta['universe_n']} symbols")


def main():
    p=argparse.ArgumentParser(description="Independent Asia GARP research-only scanner")
    p.add_argument("--universe",type=Path,default=Path("data/universe.csv"))
    p.add_argument("--output",type=Path,default=Path("outputs"))
    p.add_argument("--max-symbols",type=int,default=0,help="0 = entire curated universe")
    p.add_argument("--delay-seconds",type=float,default=1.0)
    args=p.parse_args()
    run(args.universe,args.output,args.max_symbols,args.delay_seconds)
if __name__ == "__main__": main()
