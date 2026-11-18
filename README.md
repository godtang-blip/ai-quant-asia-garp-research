# Asia GARP Research v0.5.1 — Five-Market Coverage & Evidence-Gated Research

> **Research-only independent project.** No trading, brokerage orders, allocations, or investment recommendations. Not affiliated with Redpoint Partners or any financial institution. Developed with AI coding assistance; human researcher remains responsible for all numbers, classifications and decisions.

**One repository, ONE active GitHub Actions workflow, one execution covering all existing research stages plus v0.5.1 coverage and source-quality audits:**

1. **DISCOVERY** — Five Asian equity markets (Korea, Japan, China, Hong Kong, Taiwan), curated + actual source-discovered symbols, provenance, basic vendor screening and market balance. In `all5_official`, the pipeline *attempts* official Japan JPX, Taiwan TWSE, optionally Korea KRX with a data.go.kr API key, official Nikkei index, and five vendor regional screeners. China and Hong Kong listing discovery still depends on the vendor screener; not a census. Source failures are logged, not replaced with fictional tickers.
2. **EVIDENCE** — Dated news **headlines only**, vendor quarterly financial rows, optional regulator DART **filing index** (Korea) and explicitly analyst-attested reconciliations of primary filing numbers. Financial statement comparisons must have the same period, units, a dated official/issuer source locator, a reviewer and <=2% deviation. Nothing is automatically counted as filing verified merely because a URL exists.
3. **VALUATION + MEMO** — Three manually specified FCFF DCF scenarios (bear/base/bull), strongest opposing evidence, catalyst, falsification rule, analyst accept/reject decisions, and a per-company research memorandum. The engine does not invent growth forecasts or supply a target price when model inputs are absent. Only reviewed hypotheses pass the final stage.

**Important: This version upgrades research *process auditing*, not demonstrated stock-picking quality.** Its new quality tests cannot establish predictive power or future return outperformance.

## Five-market coverage follow-up

The `all5_official` workflow now supports dated exchange exports alongside the
live JPX, TWSE, and optional KRX connectors. The fetch cap reserves research space for each market before assigning the
remaining slots by available ticker count. The coverage audit reports listing membership,
vendor financial availability, and screening eligibility separately. See the
[coverage audit, source matrix, and export instructions](docs/FIVE_MARKET_COVERAGE.md).
The market-only investigation queue is exported separately in
`46_market_stratified_research_queue.csv`. The history below describes each
original release and its observed results.

## Version History — Problems Encountered, Why They Mattered, and What Changed

This project did not begin as a finished investment model with known answers. It evolved by **documenting observed failures, sampling biases, and gaps in evidence verification**, then adjusting the research process in response. The figures and validation status below refer to the observations or implementations available at each release. Changes in scores or universe size **must not be interpreted as improved investment returns**.

| Version | What Was Implemented or Tested | Observed Problem and Rationale for the Next Version | Changes Introduced / Remaining Limitations |
|---|---|---|---|
| **v0.1 — Initial experiment** | Tested GARP-style screening on a small company set, combining growth and valuation metrics. | The candidates clustered in semiconductors, and some Yahoo Finance-derived financial metrics appeared unreliable. Standalone scores were insufficient for robust cross-company comparisons. | **v0.2** introduced industry peer groups and explicit data-quality warnings. |
| **v0.2 — Peer-group expansion** | Expanded to a curated universe of 61 companies, with industry peer comparisons and financial-data warnings. | Potential mismatches in currencies and statement units for Hong Kong-listed issuers, together with uncertain fiscal periods and P/E inputs, could distort comparisons. | **v0.2.1** strengthened outlier quarantine and currency-related safeguards instead of assuming that every available number was comparable. |
| **v0.2.1 — Anomaly quarantine** | Conservatively excluded or quarantined suspect indicators and documented unknown currencies or reporting periods. | A preselected universe could not systematically uncover unfamiliar companies. A common, defensible framework for prioritizing research across industries was also needed. | **v0.3** attempted broader automated discovery, industry-aware research-priority scoring, and FX/accounting-standard audits. |
| **v0.3 — New-issuer discovery** | One observed run returned **416 companies**, including **355 newly discovered names**. Introduced 100-point, industry-sensitive screening and FX/accounting checks. | The sample was geographically unbalanced: **272 of 416 companies were Japanese**, versus **one mainland China company**. All **355 newly discovered companies** were excluded from the research shortlist under the then-current rules. Primary-filing numerical reconciliations had not been established. | **v0.3.1** added five-market discovery attempts, region-balanced sampling, provisional eligibility for new names, and source/counterevidence records. |
| **v0.3.1 — Provenance and counterevidence** | Added discovery across Korea, Japan, mainland China, Hong Kong, and Taiwan; withheld EPS-based P/E when currency units were unclear; included news headlines, vendor financial extracts, a DART **filing index**, manual `REJECTED` decisions, and same-input weighting sensitivity checks. | The archived run reported **684 companies analyzed / 623 scored / 94 research candidates / 287 anomaly warnings**, but **zero financial figures reconciled against primary filings**. Even high-scoring candidates lacked the documented evidence and valuation work needed for an investment thesis. | **v0.5** connected financial-statement reconciliation, evidence stage gates, three valuation scenarios, opposing evidence, and research memoranda into one auditable pipeline. |
| **v0.5 — Integrated three-stage workflow** | Joined five-market discovery, evidence collection/reconciliation, and valuation/memo preparation in **one GitHub Actions run**. Added public exchange-listing adapters, manual evidence attestation, counterevidence requirements, and falsification conditions. | A more rigorous process does **not** establish stronger future stock-selection accuracy. Direct verification of primary-filing figures and analyst-supplied assumptions are still necessary. | Re-applied the new gates to the **unchanged archived v0.3.1 results**: `SCREENED 94 / EVIDENCE_CHECKED 0 / VALUATION_REVIEWED 0 / MEMO_READY 0`. This demonstrates that **unsupported promotion was blocked**, not that returns improved. |
| **v0.5.1 — Country-bias and evidence-quality audit** | The 2026-11-18 v0.5 run investigated **1,722 issuers / 240 screening-eligible**, but **1,121 (65.1%) were Taiwanese**. Japan JPX listing parsing failed; Korea official listing lacked an API key; mainland China and Hong Kong official listing adapters were not connected. A news item for Newborn Town referred to a different company. | Source failures and mismatched access can make five-market rankings appear more complete than they are. Broad `Electronic Components` classifications could also force unrelated issuers into an electrification peer group. | **v0.5.1** adds tolerant JPX Excel header detection (offline-tested; live publisher fetch still unverified), fail-visible five-market coverage and concentration audits, separate global/market research queues (not portfolio quotas), conservative component classification, headline issuer-match quarantine, and high-score rejection review. **No automatic China/HK issuer census, machine-parsed primary financials, or independently validated stock-picking edge** is claimed. |

### Research Implications and Validation Boundaries

- **Broader discovery is not the same as higher research quality.** The observed progression of 61 → 416 → 684 companies reflects changes in search coverage. Different universes, timestamps, and source snapshots prevent controlled claims of performance improvement.
- **A screening score is not an investment recommendation.** Since v0.3, the 100-point score has represented a *priority for further investigation*. Its ability to predict future excess returns has not been validated.
- **An official listing is not an audited financial statement.** Discovering an issuer through an exchange listing does not verify its financial metrics. In v0.5, `EVIDENCE_CHECKED` requires analyst-attested reconciliation of figures, reporting periods, and units against an actual primary filing.
- **Reproducibility tests are not tests of alpha.** Automated tests and same-input sensitivity checks examine code and process behavior. Return validation would additionally require point-in-time data, controls for survivorship and look-ahead bias, and genuinely out-of-sample tracking.
- **Maintain the investigation trail.** [`CHANGELOG.md`](CHANGELOG.md) records release-level changes; [`docs/README_v031_legacy.md`](docs/README_v031_legacy.md) preserves the original v0.3.1 documentation. Observed results, implemented controls, and unresolved claims must remain clearly differentiated.

## GitHub installation (existing repository; no new repository needed)

1. Download the **full v0.5.1 GitHub repository ZIP** and unzip it. Copy the **contents** of the inner `ai-quant-asia-garp-research/` folder onto the root of your current `ai-quant-asia-garp-research` GitHub repository. Back up your existing repository first. Include the hidden `.github/` folder. Commit/push using GitHub Desktop (or Git). Do **not** alter your separate `ai-quant-v512-paper` account repository or its `state/latest.zip`.
2. **Retire the old v0.3.1 workflow before pushing:** delete `.github/workflows/run-research.yml` from your **existing local repository**. Keep `.github/workflows/run-research-v05.yml`. Copying/unzipping v0.5.1 over an existing directory **does not delete** old files; without this deletion GitHub will show two runnable workflows. This is only an obsolete **Actions configuration**. Keep `src/v031.py`, `src/discovery_v031.py`, and `docs/v031-legacy-workflow.yml.txt` because the v0.5 Python engine calls v0.3.1 internals, and the historical source/documentation must remain reproducible. GitHub Desktop should show the deleted YAML file in **Changes**; include it in the Commit and Push. Do not delete or edit other repositories or account state.
3. In GitHub open **Actions → Asia GARP v0.5.1 | 5 Markets + Evidence + Valuation (Research Only) → Run workflow**. Use `max_symbols=150`, `discover_mode=all5_official`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`. GitHub Action automatically runs all offline regression and quality-gate tests first.
4. After a successful run, download the `asia-garp-v051-<run-id>` Artifact ZIP from the Actions run. The most useful files are `38_market_coverage_audit.csv`, `39_market_research_queue.csv`, `40_news_relevance_audit.csv`, `41_high_score_recheck_queue.csv`, `42_research_readiness_v051.json`, `43_quality_diagnostics_v051.md`, `44_v051_run_manifest.json`, plus legacy `03_research_report.md`, `12_discovery_sources_log.csv`, `22_evidence_sources_log.csv`, `32_research_stage_gate.csv`, `33_analyst_memoranda.md`, `34_research_quality_v05.json`, `35_quality_upgrade_comparison.md`, `36_official_exchange_source_registry.csv`.
5. **Preserve any existing analyst edits** in `data/research_decisions.csv`, `data/verified_financials.csv`, and `data/valuation_assumptions.csv` when upgrading; the bundled templates are intentionally empty. To verify official filings yourself, edit the two **blank** CSV templates `data/verified_financials.csv` and `data/valuation_assumptions.csv`, plus existing `data/research_decisions.csv`. Commit them and re-run. Empty data are intentional: no false verified recommendations.

**Optional Secrets** in Repository Settings → Secrets and variables → Actions:
- `DART_API_KEY`: Korean OpenDART filing *index*, not verified numerical statements.
- `PUBLIC_DATA_API_KEY`: Korean financial-regulator/KRX listed-securities *identifier* listing via data.go.kr. Requires approved API access. Optional `KRX_BASE_DATE` **Actions variable** `YYYYMMDD` for exchange holidays; otherwise the code requests previous weekday (which can be a Korean exchange holiday and correctly fail).

**No secret** is required for vendor-only regional screeners, JPX, TWSE, news headlines or local quality checks. Some publisher sites can refuse GitHub-hosted requests or change formats; read logs and do not infer complete official coverage from an empty feed.

## v0.5.1 — What changed and what remains unverified

**Observed input, not an investment result.** The supplied `asia-garp-v05-44291455708(1).zip` contains 1,722 investigated companies, including 1,121 Taiwan names. Its official source log shows TWSE **1,093 rows accepted**, JPX **schema error**, KRX **not configured**, China/Hong Kong **no official connector**. Taiwan's larger candidate volume therefore cannot be read as proof of better Taiwanese fundamentals. Reprocessing these frozen v0.5 artifacts with the new v0.5.1 audit produces `PARTIAL_COVERAGE` and preserves the original investment stage counts (0 evidence-checked/memo-ready). This is a **retrospective process audit**; it does not prove JPX works online yet.

The **same active workflow** `run-research-v05.yml` now calls `python -m src.v051`. The base v0.31 screening and v0.5 reconciliation/DCF logic remains part of the execution. The extra artifacts are:

| File | Purpose | Interpretation |
|---|---|---|
| `38_market_coverage_audit.csv` | Discovered vs selected vs scored vs eligible per market, and status of each official listing source | Warns on gaps, does not claim full exchange coverage |
| `39_market_research_queue.csv` | One global investigation queue plus up to five *review* names per market | Research attention allocation, **not** five-country equal-weight investments |
| `40_news_relevance_audit.csv` | Explicit ticker/name headline-match or quarantine status | Headline **only**; matching name does not verify the article |
| `41_high_score_recheck_queue.csv` | Failed screening-gate candidates with high numerical scores | **Recheck**, do not auto-buy or bypass flags |
| `42_research_readiness_v051.json` | Machine-readable quality status, concentration, news quarantine and validation boundaries | `PARTIAL_COVERAGE` is visible even on a technically successful Action |
| `43_quality_diagnostics_v051.md` | Analyst-readable brief with coverage and remediation | Operational quality, not realized investment performance |
| `44_v051_run_manifest.json` | v0.5 output and v0.5.1 audit merged | All prior output files retained for traceability |

**JPX parser:** supports English and Japanese market-section headers, plus date/title rows in Excel. If no valid market type is detected, it fails visibly rather than treating an ETF as a domestic common share. Numeric 4-digit securities only; alphanumeric securities remain excluded. Offline regression tests validate representative schema variants, **not** the publisher's current live file.

**Industry classification:** Vendor labels like `Electronic Components` or `Electrical Components` are broad. Newly discovered names with these labels are left `unclassified` until the analyst identifies the end market and appropriate peer group. A lower eligible count resulting from more conservative classification is **not automatically a regression**.

**Important current limits:** The system does *not* implement official mainland China or Hong Kong whole-market listing adapters, does *not* require that all official feeds work for CI success (instead issues a GitHub `PARTIAL_COVERAGE` warning), does *not* automatically read or reconcile primary filings, and does *not* contain a validated LLM investment researcher. Do not call the project production-ready or predictive until verified data and prospective outcomes exist.

For the first new GitHub run, use `max_symbols=150`; this provides an approximately balanced **sample** of discovered candidates, not a complete market census. `max_symbols=0` may exceed hosted-runner time and vendor rate limits once JPX is repaired. Compare `discovered_universe_share_pct` with `analysis_share_pct` rather than assuming a capped sample removes source bias. Set optional `PUBLIC_DATA_API_KEY` to enable Korean official listing requests after obtaining permission from data.go.kr.

## Version 0.5 quality gate: explicitly measurable

| Label | Meaning | Minimum evidence | Automated? |
|---|---|---|---|
| `REVIEW_REQUIRED` | Screening rejected or insufficient | Screening output / source logs | Yes |
| `SCREENED` | Investigation-priority candidate; NOT buy-rated | Pass existing v0.31 anomaly / coverage / equity-type checks | Yes |
| `EVIDENCE_CHECKED` | Manual **attestation** of 3 reconciled metrics, one fiscal period | Revenue + profit or cash flow + one other metric, exact vendor/filing period, currency/unit, filing URL, page/line, filing date, reviewer; <=2% numeric difference | Verify format/gates automatically; **read filing manually** |
| `VALUATION_REVIEWED` | Full signed scenario inputs and research counters | DCF bear/base/bull, same currency, source date and URL, explicit thesis, catalyst, bear case, counterevidence, falsification rule | Calculates from entered numbers; **assumptions manually set** |
| `MEMO_READY` | A sourced reviewed analyst thesis, not a trade | All previous gates + `ACCEPTED` decision and reviewer signature with reasons, counterevidence and revisit trigger | Gate automatic; **decision manual** |

**The new CI asserts gate behavior, not future investment returns.** Financial comparisons with mismatched reporting dates, missing documentation, or >2% uninvestigated differences **fail closed**. Empty CSVs produce zero `EVIDENCE_CHECKED`, `VALUATION_REVIEWED`, `MEMO_READY` names. A signed record is only as accurate as the human reading the source filing; the system does not independently parse every issuer PDF.

### Verified prior-run baseline, used as a smoke check

For the actual archived v0.3.1 result dated 2026-11-18: **684 analyzed**, **623 score available**, **94 screening-eligible**, **287 metric anomaly warnings**, **0 numbers reconciled to primary source**. Applying the new gate logic to that unchanged historical result yields: `SCREENED 94`, `EVIDENCE_CHECKED 0`, `VALUATION_REVIEWED 0`, `MEMO_READY 0`. This accurately describes incomplete verification; it does not prove investment accuracy has increased.

## Local tests and optional replay

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m src.v051 --discover-mode all5_official --max-symbols 150 --per-region 90 --fx-mode live --evidence-mode full --evidence-limit 8 --output outputs

# Historical vendor input: no fresh universe, news, FX, filings
python -m src.v051 --discover-mode off --fx-mode off --snapshot-csv snapshot.csv --max-symbols 0 --evidence-mode off --output replay_outputs
# If analyst evidence is used in replay, specify the genuine snapshot cutoff:
python -m src.v051 --discover-mode off --fx-mode off --snapshot-csv snapshot.csv --asof-date 2026-09-30 --output replay_outputs
```

Replay without explicit `--asof-date` **disables promotion from external analyst reviews** to prevent obvious time mixing. Even with an as-of date, historic vendor data and issuer universe are not proven point-in-time complete; no historical return backtest is performed.

## Evidence and valuation caveats

- `data/verified_financials.csv` requires **one row per exact official/vendor metric comparison**. Each row's `primary_value` and `vendor_value` must be in the **same explicit** currency/unit and exactly matching reporting periods; `filing_page`, `statement_label`, `filing_date`, `filing_url`, and `reviewer` must be provided. `review_status=CONFIRMED` is your attestation that you actually read the filing. This code cannot infer scaling such as millions vs billions; you must convert both values first. Do not enter fake test values into actual research files.
- `data/valuation_assumptions.csv` uses **raw currency units** for `fcff_year0` and `net_debt`, and **raw number of shares** for `shares_outstanding`, so DCF yields local currency **per share**. Do not mix millions in one field with unscaled numbers in another. Calculations are illustrative, model-sensitive and can be dominated by terminal value; prefer source-linked sustainable cash flows.
- Not all issuers have reliable positive FCFF; there is **no automatic DCF** for companies lacking reviewed assumptions. A DCF is not intrinsically superior to multiples, SOTP, or residual income for all industries; other models are not implemented in this version.
- `data/research_decisions.csv` preserves `REJECTED` and `ON_HOLD` theses. Code cannot change analyst opinions; `ACCEPTED` must include complete primary evidence and a counterargument.
- FX conversion continues the explicit v0.31 proxy logic, **not IAS 21-compliant financial statement restatement**. Cross-currency EPS is still withheld when units are unknown. Industry reference anchors are uncalibrated.
- Official universe listings are **issuer identities**; they do not verify issuer financial statement data. Japan JPX numeric-only parser excludes its alphanumeric listings; Taiwan TWSE excludes TPEx; Korea KRX requires credentials; China and Hong Kong official issuer adapters are not implemented. Vendor-only discovery remains a partial subset, not a census.
- Newspaper RSS returns **unread headline metadata**, not verified news claims. No LLM is allowed to invent facts or automatically set investment decisions.

See `docs/QUALITY_SPEC_V05.md` for exact fields and `docs/README_v031_legacy.md` for historical engineering lineage.

## Why there is only one active GitHub Actions workflow

The prior `run-research.yml` executed the standalone v0.3.1 analysis. It was a **legacy version**, not a stage that v0.5 requires you to run manually. The single active `run-research-v05.yml` now invokes `src.v051`, which invokes `src.v05` (and, in turn, `src.v031`), preserving earlier screening and evidence gates while adding v0.5.1 audits. Running both separately wastes API requests and may produce confusing outputs from different versions. The original v0.3.1 workflow is preserved as an **inactive historical text file** at `docs/v031-legacy-workflow.yml.txt`, not under `.github/workflows/`.

When upgrading an existing checkout, verify with `dir .github\workflows` (Windows) that **only `run-research-v05.yml`** remains. **The filename intentionally stays the same to avoid a second workflow.** The regression tests now explicitly fail if another `.yml` or `.yaml` workflow remains active. Existing historical GitHub Actions run records may remain visible in the GitHub UI, but only the v0.5.1 workflow will be dispatched from the current repository files.
