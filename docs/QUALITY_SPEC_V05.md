# v0.5 — Research Quality Specification (auditable, no simulated verification)

## 1. Baseline & measurement

Actual v0.3.1 archive (2026-11-18): analyzed=684, rankable=623, research_eligible=94, warnings=287, verified_primary_numeric=0, news_headlines=30, vendor_quarters=28. All re-run comparisons must preserve **same input, time and universe** where possible. A larger universe or more evidence metadata is not proof of increased accuracy.

## 2. Official listing identification

- JPX exchange monthly XLSX: domestic Prime/Standard/Growth names with 4-digit numeric symbols only; suffix `.T`. Exclude ETFs, REITs, foreign stocks, ambiguous listings. Alphanumeric issue codes currently not parsed; limitations count against completeness.
- TWSE issuer-list Open API: listed companies only, `.TW`. TPEx not included.
- Korea KRX listed information: optional authenticated Government Financial Services API, parsed with KOSPI `.KS` and KOSDAQ `.KQ`; default last weekday (holiday risk). API key stored in GitHub Secrets.
- China mainland, Hong Kong: no authenticated official directory download in this version; Yahoo regional screener discovery continues with visible vendor source. Do not mark exchange universe complete.
- All sources: fail closed, keep logs with source `OK` / `FAILED_NO_FALLBACK` / `NOT_CONFIGURED_AUTH_REQUIRED`. A found ticker still needs issuer & security-type verification.

## 3. Primary-source numeric verification (manual attestation + machine gates)

Populate `data/verified_financials.csv` with rows containing:

| Field | Meaning |
|---|---|
| ticker, metric | Exact security and `revenue`, `operating_income`, `net_income`, `operating_cashflow`, `free_cashflow`, `total_assets`, `diluted_eps`, or `share_count` |
| primary_value, vendor_value | Same denominator, same scale, both finite values; code rejects >2% relative difference |
| currency, unit | Explicit issuer financial-currency code and shared number unit (e.g. KRW for unscaled raw won, USD for unscaled raw dollars); values must already have the same scale |
| fiscal_period_start/end, vendor_period_start/end | Exactly matching YYYY-MM-DD ranges; method does **not** infer quarter/year periods |
| filing_date, filing_url, filing_page, statement_label | Date and precise primary issuer/regulator URL and locator to the actual filing row |
| source_type, review_status, reviewer | `ISSUER_FILING` or `REGULATOR_FILING`, manually set `CONFIRMED`, actual responsible analyst |

Missing or future-dated filing, mismatched fiscal dates, wrong value units, non-primary sources, or lack of reviewer => `BLOCKED`. Three **distinct** reconciled metrics in the **same** period and currency, including revenue and an earnings/cashflow metric, are required to count as `EVIDENCE_CHECKED` (and only if v0.31 screening eligibility also passed). Duplicated rows do not count twice. Automatic authenticity checking of the source URL contents is **not** implemented.

## 4. Valuation scenarios

`data/valuation_assumptions.csv` contains one row per ticker with:

- ticker; `asof_date`, currency, FCFF `fcff_year0`, shares_outstanding, net_debt, current_price.
- `growth_bear`, `growth_base`, `growth_bull`, discount_rate, terminal_growth, forecast_years (3..10).
- Issuer `filing_url`, reviewer and five meaningful explanatory fields: thesis, catalyst, bear_case, counterevidence, falsification_trigger.

For each growth case, FCFF evolves multiplicatively for each of N years, annual flows are discounted at rate r, terminal value is year-N FCFF × (1+g_terminal)/(r−g_terminal), and equity value equals PV(FCFF+terminal)−net_debt, divided by shares outstanding. All inputs use **identical raw local currency units**; output is local-currency per share. This simplified FCFF scenario model does not model changing margins, taxes, reinvestment or dilution, and is inappropriate if FCFF is negative. Do not present results as fair values without source and reasonableness discussion. The automatic test checks numerical constraints, not economic truth.

## 5. Memo-ready gate

The system only marks `MEMO_READY` if:
1. The existing screening gate succeeds.
2. Three matched-period primary numbers pass manual attestation checks.
3. A reviewed, source-linked three-case scenario with relevant counterevidence exists in the same currency.
4. `data/research_decisions.csv` has the analyst's `ACCEPTED` decision with date, rationale, URLs, reviewer, original thesis, counterevidence and revisit trigger.

An analyst's `REJECTED` decision remains a useful substantive conclusion but never becomes investment-ready. Any missing precondition leaves an explicit `blocking_reasons` string in `32_research_stage_gate.csv`. The system does not auto-accept proposals.

## 6. Research validity yet to be established

- Publisher listing source success may fail on GitHub network; there is no automatic replacement using guessed tickers.
- Manually entering correct-looking numbers is not independent machine auditing; figures could be wrong if reviewer misreads PDFs.
- Vendor data can have survivorship, symbol changes, splits, period misalignment, and accounting differences; v0.31 warnings remain applicable.
- Date-filtered manual evidence on snapshot replay helps prevent leakage but does not establish truly point-in-time vendor fundamentals.
- The pipeline has not measured future alpha, hit rate, precision, or realized excess returns. To make those claims, build timestamped prospective predictions and true out-of-sample outcomes.

## 7. File map

- `01`–`29`: v0.31 existing outputs preserved exactly for regression/audits.
- `30_primary_financial_reconciliation.csv`: each submitted row with exact blocker tags.
- `31_valuation_scenario_audit.csv`: three DCF scenario results or blocked inputs.
- `32_research_stage_gate.csv`: stage, quality blockers, explicit human decisions.
- `33_analyst_memoranda.md`: source-sensitive candidate notes, including opposing argument.
- `34_research_quality_v05.json`: machine-readable counts, explicit unverifiable areas.
- `35_quality_upgrade_comparison.md`: v0.31 baseline and new gates; no predictive claims.
- `36_official_exchange_source_registry.csv`: official adapter implemented / not connected and actual attempt results.
- `37_v05_run_manifest.json`: full metadata.
