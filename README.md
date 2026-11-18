# Asia GARP Research — Five-Market Equity Discovery

An independent, AI-assisted research project that looks for growth at a reasonable price (GARP) across Korea, Japan, mainland China, Hong Kong, and Taiwan. The goal is to discover companies worth investigating and give an analyst enough evidence to challenge the screening result. The workflow places no trades and makes no investment recommendations.

1. **Discover** listed securities and record where each ticker came from.
2. **Screen** for research priority using financial data, industry context, and quality checks. The audit separates discovered securities, names with usable financial data, scored names, and eligible candidates.
3. **Review** candidates against primary filings, valuation scenarios, and contrary evidence. An analyst must reconcile figures and document a decision before a candidate can reach the memo-ready stage.

## Latest completed full-universe run

The GitHub Actions run analyzed **5,098 securities**. Of these, **4,800 received a score** and **589 passed the initial research screen**.

| Market | Securities analyzed |
|---|---:|
| Korea | 99 |
| Japan | 3,686 |
| Mainland China | 91 |
| Hong Kong | 101 |
| Taiwan | 1,121 |
| **Total** | **5,098** |

JPX and TWSE listing ingestion succeeded in that run. JPX's wider listing file brought many more Japanese securities into discovery and exposed gaps in Korea, mainland China, Hong Kong, and Taiwan's TPEx segment. “Full-universe” here means the run analyzed the available discovery universe. Exchange scope still requires independent verification.

## GitHub Actions discovery smoke tests

With `max_symbols=20`, the smoke test discovered **7,593 unique security codes** before the limit on financial-data fetches. JPX accepted **3,686**, the HKEX workbook accepted **2,781 of 17,355 rows**, and TWSE accepted **1,093**. Source counts can overlap with curated and vendor discovery. The earlier 5,098 figure counts analyzed securities from a different run.

A subsequent reported smoke test discovered **8,489 securities**, with live retrieval from JPX, HKEX, TWSE, and TPEx. This confirms the TPEx fix on Actions. Source-level counts for this newer run were not supplied. The 7,593 total above is from the preceding smoke test.

A later reported Actions run discovered **11,052 securities**, including **2,590 from Korea KIND**. Mainland China still had no successful live listing source. SSE and BSE returned HTTP 403, and SZSE's workbook reset its connection before the JSON fallback returned HTTP 500.

The next reported listing-only Actions run discovered **11,051 securities**, with zero new mainland China listings. SSE Main Board and STAR failed pagination validation, SZSE failed on both routes, BSE returned HTTP 403, and BaoStock timed out. The current branch uses AKShare's observed SSE request shape with strict publisher-total checks and bounded response diagnostics. That change is fixture-tested. Its live response remains unverified. BaoStock now checks its TCP endpoint before starting the SDK. [SSE diagnostics and fallback findings](docs/CHINA_A_SHARE_DISCOVERY.md#sse-pagination-follow-up)

The HKEX adapter keeps its existing Main Board and GEM equity category filters. It preserves separate share classes and trading counters, including different currency counters with different security codes. The 2,781 figure counts accepted security codes. An issuer can contribute several codes. The source log now reports workbook exclusions by category and subcategory, separately from duplicate rows and invalid symbols.

## Current Status and Remaining Limitations

The Korea and mainland China changes below are separate from the latest successful Actions retrievals. The discovery-only cloud check returned **zero accepted live Korean securities** and **zero accepted live mainland Chinese securities**. The proxy returned CONNECT 403 for the publisher routes. Credited listings, source scope and common-equity eligibility still need validation.

| Market | Automated routes in official discovery mode | Verified scope and remaining inputs |
|---|---|---|
| Korea | KRX listed-issue API, plus independent public KIND KOSPI and KOSDAQ company downloads | KRX needs `PUBLIC_DATA_API_KEY` and optionally a trading-date override. KIND uses no API key; both market downloads were blocked in the cloud. OpenDART with `DART_API_KEY` can annotate issuer identity for already discovered tickers and does not establish listing membership or security type. Dated KOSPI/KOSDAQ publisher exports are the manual fallback. |
| Mainland China | SSE Main Board and STAR A-share queries, existing SZSE A-share workbook with a JSON route after a transient/workbook failure, and the BSE listed-company table | All new routes are fixture-tested. The Actions SZSE workbook reset its connection in the earlier smoke test; the cloud proxy denied the workbook, JSON route, SSE, and BSE. B shares and NEEQ-only listings are outside the configured scope. The new routes need no exchange credentials. Dated SSE, SZSE and BSE publisher exports remain supported. |

JSON pagination rejects incomplete or repeated pages. The SZSE alternate route is skipped when the workbook succeeds or access is explicitly denied or rate-limited. Publisher matches are listing candidates and still face the existing vendor security-type checks. The objective remains genuine five-market discovery without country quotas.
- **Separate cloud observation.** An earlier cloud probe retrieved **zero external securities** and carried forward **61 existing curated names**. That probe and the Actions runs used different environments.
- **Candidate follow-up.** The review tool preserves the original scores and decisions while separating fundamental failures from potentially recoverable exclusions, such as missing financials, unresolved industry classification, or data-quality flags. It can compare the original screen with a separate rerun on corrected inputs. Automated data repair and autonomous reassessment remain open work. The Korea investigation queue is separate from global rankings.
- **Filing research in development.** Gemini v0.5.2 is a separate feature branch for source-grounded filing research. It has yet to be integrated, and the active GitHub Actions workflow performs no live Gemini analysis. [Gemini development branch](https://github.com/godtang-blip/ai-quant-asia-garp-research/tree/codex/gemini-filing-research-v052)

## Run the research workflow

In GitHub, open **Actions → Asia GARP v0.5.1 | 5 Markets + Evidence + Valuation (Research Only) → Run workflow** and select the branch to run. Start with `discover_mode=all5_official`, `max_symbols=150`, and the default FX and evidence settings. The cap limits financial-data fetches. Set `max_symbols=0` to attempt every discovered security, subject to source and runner limits. For a targeted smoke test, use `max_symbols=20` with `fx_mode=off` and `evidence_mode=off`. The workflow passes these choices as strings to the CLI.

| GitHub Actions setting | Purpose |
|---|---|
| Secret `PUBLIC_DATA_API_KEY` | Authorized data.go.kr key for the KRX listed-issues connector |
| Secret `DART_API_KEY` | Optional OpenDART filing index access for Korean issuers |
| Variable `KRX_BASE_DATE` | Optional trading-date override in `YYYYMMDD` format |
| Variable `GARP_LISTING_EXPORT_DIR` | Optional checkout-relative directory containing validated, dated exchange exports |

For local execution, use the same names as environment variables and run from the repository root.

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m src.v051 --discover-mode all5_official --max-symbols 150 --output outputs
```

### Validate listings without fetching financials

On a runner with approved exchange access, run:

```bash
python -m src.discovery_smoke --output discovery-smoke
```

The command runs official sources, the independent BaoStock security master, and configured exports. It records per-route errors and provenance and skips Yahoo discovery and all fundamental fetches. In GitHub Actions, enable `discovery_only` for the same behavior and downloadable reports. The cloud test reached no live mainland China listings, including BaoStock, whose native SDK failed at login with network receive error `10002007`. AKShare's investigated functions reuse the official exchange routes. [Source-by-source results and an authorized snapshot option](docs/CHINA_A_SHARE_DISCOVERY.md) Inspect `12_discovery_sources_log.csv` and `47_venue_coverage.csv`. For Korea, compare the distinct KIND KOSPI and KOSDAQ results with the dated exchange scope, then cross-check the KRX route if a key is available. For mainland China, check SSE Main Board and STAR separately, confirm SZSE workbook or JSON completion, and verify that BSE results exclude NEEQ-only securities. After verifying each source, a 20-symbol run of the existing workflow can test vendor and screening integration. [Exchange scope and export format](docs/FIVE_MARKET_COVERAGE.md)

### Read the results

Download the workflow artifact or open the local output directory.

| Output | What it tells you |
|---|---|
| `11_discovery_universe.csv` and `12_discovery_sources_log.csv` | Which securities were found, which source supplied them, and where retrieval failed |
| `38_market_coverage_audit.csv` and `47_venue_coverage.csv` | Market-level discovery and financial-data availability, plus venue-level listing evidence in official discovery mode |
| `01_all_research_candidates.csv` and `32_research_stage_gate.csv` | Original screen results and progress through evidence, valuation, and analyst review |
| `46_market_stratified_research_queue.csv` | Market-level investigation priorities alongside the existing global ranking outputs |

Create the separate coverage and exclusion reports with `python -m src.discovery_review outputs review`, where `review` is a new directory. Add `--reassessed-artifacts path/to/rerun` to compare with a completed rerun of the unchanged screen. The review writes `candidate_lifecycle.csv`, `recoverable_exclusion.csv`, `korea_investigation_queue.csv`, and, when supplied a rerun, `reassessment.csv`.

For source specifications and analyst review requirements, see the [exchange-export guide](docs/FIVE_MARKET_COVERAGE.md) and [evidence and valuation specification](docs/QUALITY_SPEC_V05.md). Screening eligibility is the first research gate. The project has yet to establish predictive performance or out-of-sample investment returns.

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

See the [changelog](CHANGELOG.md), [v0.5 retrospective audit](docs/V051_RETROSPECTIVE_AUDIT.md), and [archived v0.3.1 documentation](docs/README_v031_legacy.md) for the earlier runs and experiments.
