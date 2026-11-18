# Asia GARP Research — Five-Market Equity Discovery

An independent, human-directed project for finding Asian equities worth researching under a growth-at-a-reasonable-price framework. The pipeline covers discovery, financial screening, and evidence review across Korea, Japan, mainland China, Hong Kong, and Taiwan. Its output is a prioritized research queue. Investment conclusions remain with the researcher.

## Verified Results and Current Limitations

- **Financial-research run:** 5,098 securities analyzed, 4,800 scored, and 589 passed the initial research screen.
- **Later discovery-only GitHub Actions run:** 13,370 unique securities found. This run measured listing discovery. It did not measure financial-data availability or screening eligibility.

| Market | Securities discovered | Evidence from the discovery-only run |
|---|---:|---|
| Korea | 2,592 | 2,590 from KRX KIND |
| Japan | 3,686 | JPX live retrieval |
| Mainland China | 2,320 | 1,700 SSE Main Board and 619 SSE STAR securities retrieved live |
| Hong Kong | 2,781 | HKEX live retrieval |
| Taiwan | 1,991 | TWSE and TPEx live retrieval |
| **Total** | **13,370** | Unique security codes across the five markets |

Both SSE requests returned one complete page with publisher totals matching the accepted rows. An independent comparison with date- and scope-matched exchange statistics remains open. Security codes can include multiple share classes or trading counters for a single issuer. [China source evidence and remaining gaps](docs/CHINA_A_SHARE_DISCOVERY.md#sse-live-verification-and-remaining-szsebse-gaps)

**Still unresolved:** Live SZSE Main Board, ChiNext, and BSE acquisition. The optional Tushare routes, dated imports, and connection reports support validation, but they have yet to establish live coverage for those boards. Financial-statement reconciliation against primary filings at scale, automated recovery and reassessment of excluded candidates, and point-in-time predictive and out-of-sample return validation also remain open. Gemini v0.5.2 is a separate, unmerged filing-research feature. The active workflow performs no live Gemini analysis. [Gemini development branch](https://github.com/godtang-blip/ai-quant-asia-garp-research/tree/codex/gemini-filing-research-v052)

## Development Methodology — Human-Directed, AI-Assisted Engineering

Early versions evolved through ChatGPT-assisted experimentation, Python and Google Colab prototypes, repeated runs, and GitHub Actions testing. On **November 18, 2026**, the project adopted a more structured Codex-assisted pull-request workflow. The first documented Codex PR milestone was **“Audit and improve five-market listing coverage,”** opened at **13:13 UTC** according to the project record and merged at **13:23 UTC**, as recorded in the repository's merge history. This milestone marks a change in development practice. AI assistance was already part of the earlier experimentation. [Colab prototype](notebooks/Run_Asia_GARP_Colab.ipynb) · [PR #1](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/1)

| Responsibility | Contribution |
|---|---|
| **Human researcher and project owner** | Defined the five-market GARP objective, research questions, screening rules, and quality requirements. Reviewed actual Actions results, identified shortcomings, and prioritized changes. Retains responsibility for evidence interpretation, investment theses, valuations, and conclusions. |
| **AI coding assistance** | Helped write and modify the screening and discovery software, debug exchange adapters and API responses, build tests and diagnostics, review code, and organize source-grounded filing tools. Codex tasks were directed by the project owner. |
| **GitHub Actions** | Executes the defined workflow and produces run artifacts for inspection. Workflow dispatches provide repeatable observations under the runner's actual source-access conditions. |

## Research Pipeline and Architecture

1. **Discover listings.** Combine attributed exchange listings, dated publisher exports, and clearly labeled independent sources. Keep scope and source failures visible at market and venue level.
2. **Screen financial data.** Separate discovered securities from those with usable financial observations, a score, and initial research eligibility. Scores rank investigation priority under explicit rules.
3. **Review evidence and valuation.** Reconcile selected figures to primary filings, test valuation scenarios and counterevidence, and document the human research decision. [Evidence and valuation specification](docs/QUALITY_SPEC_V05.md)

## Validation Philosophy and Quality Gates

Observed failures shaped the design. Early semiconductor concentration exposed sector and sampling bias. Inconsistent currencies and reporting periods prompted data-quality checks. Early screens rejected too many unfamiliar companies, and uneven listing access gave an impression of country concentration. Exchange failures prompted evaluation of public and authenticated routes. High scores backed by unreliable data were quarantined. SSE live retrieval followed diagnosis of the request parameters and pagination, with accepted rows reconciled to publisher totals. [Five-market discovery milestone](docs/FIVE_MARKET_DISCOVERY_MILESTONE.md) · [SSE follow-up](docs/CHINA_A_SHARE_DISCOVERY.md#sse-pagination-follow-up)

The validation layers answer different questions. Tests check software behavior. Live requests check whether a runner can access a source. Reconciliation checks data correctness and reporting scope. Screening gates determine research eligibility. Point-in-time, out-of-sample analysis would test investment performance. The project has not established alpha, realized returns, or investment recommendations.

## Roadmap

Broader, verifiable discovery across all five markets remains a priority. The following work can advance in parallel where inputs permit:

- **Financial-data integrity.** Reconcile currencies, units, periods, and selected figures to primary filings.
- **Candidate recovery.** Separate weak fundamentals from missing or unreliable data, obtain corrected inputs, and rerun unchanged screening rules. Eligible names can return to the research queue while investment theses remain subject to human approval. The current tool compares completed runs and preserves original decisions.
- **Screening-model validity.** Measure sector and country bias, test sensitivity and stability, build point-in-time datasets with survivorship and look-ahead controls, and evaluate out-of-sample results against suitable benchmarks.
- **Human-reviewed company research.** Examine the business model, growth drivers, competitive advantages, financial statements, valuation scenarios, catalysts, and counterevidence. Record falsification conditions and the final investment memorandum.

## Reproduce the Workflow

Open the [existing GitHub Actions workflow](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/workflows/run-research-v05.yml) and select the branch to run. Enable `discovery_only` to inspect listings without fetching fundamentals. Add `china_only` to focus on mainland sources and `china_provider_probe` for opt-in connection diagnostics. For a bounded financial run, use `discover_mode=all5_official` and `max_symbols=150` or smaller.

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m src.discovery_smoke --output discovery-smoke
```

Review `11_discovery_universe.csv` and `12_discovery_sources_log.csv` for listings and source evidence, `38_market_coverage_audit.csv` for research-run coverage, and `47_venue_coverage.csv` for venue scope. The China acquisition report is `52_china_acquisition_acceptance.csv`. For a completed research run, `python -m src.discovery_review outputs review` creates exclusion diagnoses and can compare a completed rerun using `--reassessed-artifacts`.

Optional configuration includes `PUBLIC_DATA_API_KEY` for authorized KRX data, `DART_API_KEY` for OpenDART, and `GARP_LISTING_EXPORT_DIR` for dated exchange files. Tushare requires entitled access or an authorized dated snapshot. The normal workflow requires explicit opt-in for token use. [Export format and coverage checks](docs/FIVE_MARKET_COVERAGE.md) · [Provider and acceptance instructions](docs/CHINA_A_SHARE_DISCOVERY.md#single-run-acquisition-acceptance)

For SZSE and BSE, the listing-only workflow can also validate and stage authorized dated snapshots from a private data repository pinned to a commit. Live retrieval for both exchanges remains unresolved. Optional representative Yahoo Finance diagnostics distinguish listing acquisition from financial-data availability. [Publisher downloads, private bundle and single-run verification](docs/CHINA_A_SHARE_DISCOVERY.md#szse-and-bse-acquisition-handoff)

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

### Discovery follow-up after PR #1

- An early completed financial run analyzed 5,098 securities, including 3,686 in Japan. JPX ingestion expanded Japanese coverage and made the remaining country gaps more visible.
- A later Actions smoke test discovered 7,593 security codes. HKEX accepted 2,781 codes from a workbook of 17,355 rows. TPEx initially failed schema validation. A subsequent 8,489-code run confirmed live TPEx retrieval after the parser was updated.
- An Actions run reached 11,052 codes, including 2,590 KIND listings, while mainland exchange routes were still failing. A subsequent listing-only run reported 11,051 codes and exposed SSE pagination validation errors. The 13,370-code result above followed the SSE request and pagination corrections.
- Separate cloud probes hit access restrictions and did not validate new live China listings. The diagnostics distinguish blocked routes, SDK timeouts, provisional BaoStock inventory and authorized imports. [Discovery and source investigation record](docs/CHINA_A_SHARE_DISCOVERY.md)

See the [changelog](CHANGELOG.md), [v0.5 retrospective audit](docs/V051_RETROSPECTIVE_AUDIT.md), and [archived v0.3.1 documentation](docs/README_v031_legacy.md) for the earlier runs and experiments.
