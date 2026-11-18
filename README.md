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

## Current Status and Remaining Limitations

- **Confirmed live retrieval.** JPX and TWSE succeeded in the completed GitHub Actions run above. In a separate, later Codex cloud probe, publisher requests hit a proxy block and vendor discovery also failed. The probe retrieved **zero external securities** and carried forward **61 existing curated names**. The two runs used different environments and measured different stages.
- **Implemented and tested with mocked responses.** The coverage branch adds public TPEx company-disclosure ingestion, an HKEX equities workbook adapter, and a SZSE A-share workbook adapter. Regression tests exercise parsing, instrument exclusions, duplicate handling, and KRX pagination. Live retrieval and publisher scope for the three new adapters remain unverified.
- **Open coverage gaps.** KRX listed-issue ingestion requires authorized data.go.kr credentials. SSE and BSE still lack live adapters. Dated exchange exports can supplement unavailable feeds. The next step is to validate the new adapters on a runner with publisher access, then check listing classes and as-of dates against published exchange statistics where possible. The objective remains genuine five-market discovery without country quotas or forced parity in the eligible list. [Venue-by-venue findings and next actions](docs/FIVE_MARKET_DISCOVERY_MILESTONE.md)
- **Candidate follow-up.** The review tool preserves the original scores and decisions while separating fundamental failures from potentially recoverable exclusions, such as missing financials, unresolved industry classification, or data-quality flags. It can compare the original screen with a separate rerun on corrected inputs. Automated data repair and autonomous reassessment remain open work. The Korea investigation queue is separate from global rankings.
- **Filing research in development.** Gemini v0.5.2 is a separate feature branch for source-grounded filing research. It has yet to be integrated, and the active GitHub Actions workflow performs no live Gemini analysis. [Gemini development branch](https://github.com/godtang-blip/ai-quant-asia-garp-research/tree/codex/gemini-filing-research-v052)

## Run the research workflow

In GitHub, open **Actions → Asia GARP v0.5.1 | 5 Markets + Evidence + Valuation (Research Only) → Run workflow** and select the branch to run. Start with `discover_mode=all5_official`, `max_symbols=150`, and the default FX and evidence settings. The cap limits financial-data fetches. Set `max_symbols=0` to attempt every discovered security, subject to source and runner limits.

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
