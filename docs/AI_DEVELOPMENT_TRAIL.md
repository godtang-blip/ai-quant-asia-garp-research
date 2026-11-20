# Human-directed, AI-assisted development trail

| Contributor | Role |
|---|---|
| **Researcher and project owner** | Set the five-market research objective and quality criteria, selected DB HiTek, specified evidence checks, and made the investment decision. |
| **ChatGPT** | Contributed substantially to the early code and Colab experiments, filing research, valuation calculations and report drafting. |
| **Codex** | Implemented owner-directed changes in code, tests and documentation, including source adapters, diagnostics and regression coverage. |
| **GitHub Actions** | Ran the configured workflow and recorded run artifacts and failures. The DB HiTek report and workbook were a separate research exercise. |

## Commits and pull requests

| Record | Change and evidence |
|---|---|
| Early ChatGPT and Colab experiments | The early watchlist concentrated in semiconductors and showed inconsistent vendor inputs. The follow-up added industry comparisons, currency and period checks, and anomaly handling. [Colab prototype](../notebooks/Run_Asia_GARP_Colab.ipynb) · [Version and run history](DEVELOPMENT_HISTORY.md) |
| November 18, 2026 KST · PR #1 | Improved five-market listing coverage and allocated financial fetch capacity across all five markets. Merged into `main` at `451485d`. [PR #1](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/1) |
| PR #2 · Gemini experiment | The v0.5.2 experiment added reproducible source-cell evidence and tests at `f786add`. It remains on a separate branch. [PR #2](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/2) |
| November 19, 2026 KST · PR #3 | Investigated SSE pagination, mainland board coverage, and direct and alternative SZSE/BSE sources. Merged at `89cdeca`. The subsequent run found 16,629 listing codes. [PR #3](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/3) · [Discovery milestone](FIVE_MARKET_DISCOVERY_MILESTONE.md) |
| PR #4 · v0.6 integration | Separate development branch for checkpointed campaigns, bounded official-filing and Gemini processing, and human review gates. `11f60a4` adds financial-definition provenance and `8b4d607` fixes an inclusive coverage boundary. The default branch still runs v0.5.1. [PR #4](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/4) · [v0.6 branch notes](https://github.com/godtang-blip/ai-quant-asia-garp-research/blob/8b4d6072adee25395930c53076121b57b5810603/README.md) |

## Failures and fixes

| Observation | Correction and remaining scope |
|---|---|
| Country and industry concentration, a TPEx schema mismatch, SSE pagination errors, and unavailable direct SZSE/BSE routes | Recorded scope and failures by source. QuantSonar remains a third-party listing source. [Source diagnostics](CHINA_A_SHARE_DISCOVERY.md) |
| Actions `#44451976790` failed on an empty news CSV | v0.6 commit `89fe8ec` distinguishes empty evidence from malformed input. [Run](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44451976790) |
| Actions `#44452826314` failed concurrent checkpoint validation | v0.6 commit `16d645b` validates the tables in one SQLite snapshot. [Run](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44452826314) |
| Aggregate `#44468923747` showed EDINET scope failures and Gemini HTTP 504 | v0.6 commit `68be877` adjusts EDINET entity and context handling and bounds retries. Later HTTP 400 request settings and diagnostics are recorded in `83f95c6`. [Run](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44468923747) |
| Vendor Forward P/E definitions were unresolved and exact 65% coverage could be misread | A separate sensitivity report retained original scores. The v0.6 fix addresses the 65% score boundary and preserves the separate 70% shortlist gate. [Boundary fix](https://github.com/godtang-blip/ai-quant-asia-garp-research/commit/8b4d6072adee25395930c53076121b57b5810603) |

Tests, source access, financial reconciliation and investment performance are distinct evidence levels. [Changelog](../CHANGELOG.md) · [DB HiTek case evidence](../case-studies/db-hitek/screening_evidence.md)
