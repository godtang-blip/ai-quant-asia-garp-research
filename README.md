# Asia GARP Research v0.3 — independent, reproducible equity research prototype

> **Research only. No actual trading, brokerage orders, portfolio returns, verified undervaluation, or proprietary methods of Redpoint Partners.**
>
> The investment questions, quality constraints, and product concept were driven by the researcher; code implementation was **AI-assisted**. The purpose is *auditable idea generation*, not to claim autonomous investment expertise or replicability of a specific firm's private process.

## Why this exists

Developed from a personal-investment experiment into an Asia-equity idea-discovery pipeline. A series of actual prototype problems prompted revisions:

- v0.1: manually chosen narrow semiconductor universe; vendor accounting/valuation discrepancies observed
- v0.2: expanded to 61 curated companies across 9 peer groups; still peer-ranking and sector cap issues
- v0.2.1: avoided treating HKD/CNY mismatches as universally invalid; quarantined known anomalies
- **v0.3: dynamic listing discovery, explicit FX audit trail, issuer accounting-basis evidence ledger, and cross-industry screening scores with declared sector adjustments**

**Portfolio value:** demonstrates a problem -> hypothesis -> implementation -> anomaly -> QA -> updated research question cycle. The output is a shortlist of *questions*, not proof of skill in predicting prices.

## Quick start: GitHub Actions

1. Upload the **contents** of this project folder (include hidden `.github/`) to the existing `ai-quant-asia-garp-research` repository. Do NOT overwrite the separately running `ai-quant-v512-paper` repo.
2. Under **Actions → Asia GARP Research v0.3 — Manual Only → Run workflow**, use:
   - `max_symbols = 90` to begin (the 61 curated names first, then up to 29 discovered)
   - `discover_mode = nikkei` (official Nikkei 225 constituent source; fallback is **not** invented if source unavailable)
   - `fx_mode = live` for dated Yahoo FX quotes, with visible warnings on failure
3. Open the completed run and download the **Artifact** `asia-garp-research-v03-<run_id>`.
4. Inspect `03_research_report.md`, `15_cross_industry_scores.csv`, `09_filing_verification_queue.csv`, `13_fx_normalization_audit.csv`, and `12_discovery_sources_log.csv`.

Other choices: `max_symbols=0` tries the **whole available watchlist**, potentially 200+ API calls and rate limits. A successful workflow does not imply all symbols had data. `discover_mode=both` adds optional Yahoo regional screening; source failures show in `12_discovery_sources_log.csv`. `off` uses only 61 curated names.

### CLI

```bash
pip install -r requirements.txt
python -m pytest -q tests
python -m src.v03 --max-symbols 90 --discover-mode nikkei --fx-mode live --output outputs
# offline replay, NO new exchange rates (avoid historical look-ahead)
python -m src.v03 --max-symbols 0 --discover-mode off --fx-mode off --snapshot-csv vendor_snapshot.csv --output replay_outputs
```

Private Colab option: `notebooks/Run_Asia_GARP_Colab.ipynb` accepts this ZIP. No GitHub token needed for local ZIP upload.

## What v0.3 actually implements

### 1) Extensible universe with source provenance

`data/universe.csv` has 61 *curated* names. `src/discovery.py` attempts an official **Nikkei 225** constituent table, and optionally a Yahoo regional equity screener (Japan, Korea, Taiwan, Hong Kong). Valid new symbols are deduplicated and logged.

**Important:** An index member list is not all Asian equities; it is *index-constrained* discovery. New issuers require analyst review of ticker identity, listing class and industry classification. Region screeners can be unavailable or incomplete; no synthetic fallback. New names are visible in `11_discovery_universe.csv`, but **automatically discovered names do not automatically qualify for a final investment idea**.

### 2) Currency conversion and FX audit

For Yahoo finance `info` fields:
- `currency` = price / market cap quote currency, `financialCurrency` = financial reporting currency.
- Rates from yfinance currency quotes, with source ticker, last rate date, 1-year historical average, and cache for each run.
- Market cap and price converted to **USD at dated spot**. Vendor annual free cash flow converted to **USD at 1-year mean FX as an approximation**, and `FCF / cap` re-derived with source/currency/assumption fields.
- If reporting and quote currencies are the same, FCF / cap can also be compared locally without USD FX, though the vendor period remains unverified.
- **No FX available, no cross-currency FCF yield. No guessed rates.** An EPS field of unknown currency is never mechanically divided into an HKD price. We do **not** claim to have restated local financial statements into USD or IFRS.
- The period of `freeCashflow` is vendor-defined: **1-year mean FX is a screening proxy, NOT audited IAS 21 translation**. Check actual fiscal cash flows and reporting dates in filings before valuing a business.

### 3) Accounting/comparability provenance (NOT automatic GAAP→IFRS restatement)

Korea, Japan, China, Taiwan, Hong Kong have different issuer-level allowed/reporting standards. It is wrong to assign J-GAAP to every Japanese issuer or IFRS to every Hong Kong issuer. The system retains a **jurisdiction hint**, but `reported_accounting_standard=UNKNOWN_PRIMARY_FILING_REQUIRED` unless an analyst supplies an explicit review entry:

`data/accounting_issuer_evidence.csv`: `ticker,reported_standard,source_url,filing_date,verified_by`

A complete row marks **the standard identified**, not that its actual financial statement line items have been harmonized to IFRS. Vendor earnings growth, operating margin and other ratios are still tagged **unverified**. Do not use them as audited apples-to-apples comparisons until reconciled to issuer filings (e.g., differing definitions of operating profit, intangible assets, leases, financial company accounts).

### 4) 0–100 cross-industry RESEARCH priority scores

`src/scoring_v03.py` explicitly declares absolute **fixed reference anchors**, sector-specific P/E and P/S anchors, and sector category weights. Five pillars (growth, profitability, valuation, cashflow/leverage, price momentum) produce a score on a **common numeric range**. Missing metrics reduce coverage/score; unclassified issuers and quality flags require human review. The top ten are ranked **without the old forced sector caps**.

> A common *numeric* scale does not establish true *economic* comparability or expected returns. These anchors and weights were not fitted or validated against forward outcomes. A 90-score company is NOT proven to beat an 80-score company. Sectors such as banks, REITs, insurers, pre-profit biotech need separate financial models, rather than forcing industrial-company valuation logic onto them.

Screens never silently pass extreme revenue growth, losses, major EPS inconsistencies, recent stock splits, or unresolved prior anomalies. `data/prior_discrepancies_to_review.csv` holds open source/period issues. Until filed source confirms, `filing_verification=NOT_PERFORMED`.

### 5) Analyst research decision loop

The automatic research shortlist is **only the first gate**:
1. Review source documents/period/currencies, including splits and diluted share count.
2. Explain the source of structural growth and compare business economics with competitors.
3. Decide whether DCF, peer P/E, EV/EBITDA, P/S, or multiple methods fit the business and explicitly acknowledge their limitations.
4. Estimate market-implied expectations and identify a **dated, evidenced** catalyst (not invented by LLM).
5. Write strongest bear case, sensitivity, invalidation, and a final human conclusion.

Use `07_investment_memo_TEMPLATE.md` and `16_analyst_research_queue.md` to work through these questions. Do not publicly claim forecasts were derived from the score alone.

## Main output files

| Output | Meaning |
|---|---|
| `01_all_research_candidates.csv` | all fetched records with raw vendor fields and QA |
| `02_research_shortlist.csv` | eligible unverified curated candidates, sorted by research score |
| `03_research_report.md` | reader-friendly reproducible results and limitations |
| `04_run_metadata.json` | timestamp, source status, count, calibration and verification caveats |
| `05_data_quality_review.csv` | unresolved issues and excluded candidates |
| `09_filing_verification_queue.csv` | primary filings and manual analyst sign-off queue |
| `11_discovery_universe.csv` | curated + newly found candidates with source |
| `12_discovery_sources_log.csv` | successful, failed and unavailable discovery sources |
| `13_fx_normalization_audit.csv` | quote and financial currencies, USD values, FX sources |
| `14_accounting_comparability_audit.csv` | issuer reporting standards, sources, period limitations |
| `15_cross_industry_scores.csv` | five component scores, weights, coverage and exclusion flags |
| `17_fx_quotes_log.csv` | FX pair provenance and failures |

### Operational and ethical limitations

- This is a one-off **current vendor snapshot**, not historical point-in-time fundamental research or a robust walk-forward backtest.
- yfinance fields are vendor estimates, not confirmed source filings, and can change or be wrong; some tickers may fail due to rate limits.
- Public repository publishing: do not commit personal API credentials, account state, proprietary research or provider-licensed datasets that cannot be redistributed. README and code can be public without mirroring underlying premium datasets.
- GitHub Actions success = runnable code, not verified financial accuracy or meaningful alpha.
- No claim of replicating Redpoint Partners' internal security selection or trading rules. Publicly discussed GARP-style questions informed a **separately designed, independent research system**.
