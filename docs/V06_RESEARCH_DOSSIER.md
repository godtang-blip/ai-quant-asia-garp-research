# Research Dossier from restored cycle 44456766424

Use the existing research workflow on the PR #4 branch. Start one Aggregate run. The workflow restores the plan and durable financial state for cycle 44456766424. It uses the existing GARP shortlist and keeps its ordering and eligibility. It performs no financial-provider batch calls. Do not dispatch Initialize or Batch for this procedure.

## GitHub Actions dispatch

Set repository variables GARP_ALLOW_FINANCIAL_CHECKPOINT_ARTIFACTS=1 and GARP_RESEARCH_DOSSIER=1. Keep any GARP_CLASSIFICATION_REGISTRY setting used for the original ranking.

| Input | Value |
|---|---|
| cycle_mode | aggregate |
| cycle_state | 44456766424 |
| cycle_market | All |
| report_limit, filing_budget | 5, 5 |
| enable_gemini, gemini_approved_only | true, false |
| gemini_max_documents, gemini_max_requests | 1, 2 |
| official_filing_requests, gemini_approved_sources | **Leave both blank** |
| full_universe, discovery_only, legacy_research | false, false, false |
| research_asof | Leave blank. Aggregate uses restored checkpoints and the report cutoff. |
| Other dispatch controls | Defaults; candidate finances come from restored state |

The single run handles restore, shortlist, filing preparation, filing acquisition, numerical checks, Gemini, and dossiers. A candidate with verified original content can use the Gemini document budget even if a higher-ranked candidate is blocked. This affects evidence collection only. The dossier records the original shortlist position.

## Required secrets and cost settings

In repository Settings → Secrets and variables → Actions, add **GEMINI_API_KEY** for the Google Gemini Developer API. Add **EDINET_API_KEY** for EDINET API v2 and optionally **DART_API_KEY** for OpenDART issuer resolution and Korean annual index leads. Store credentials as Secrets. Do not put keys in CSVs, URLs or repository variables.

Set these repository variables:

- **GARP_GEMINI_MODEL** to a Gemini model your Developer API key can use, using the exact model identifier from Google's model catalog. The workflow makes one model metadata request and checks that the model advertises generateContent before sending an approved document. A successful metadata check confirms catalog access. Live generation validation requires the recorded api_responses_received count to be positive.
- **GARP_GEMINI_MAX_COST_USD**, **GARP_GEMINI_INPUT_PRICE**, **GARP_GEMINI_OUTPUT_PRICE** to your approved positive reservation and the confirmed USD per million input and output tokens for that exact model. The workflow keeps the request and token reservation limits active. Estimated cost uses the API usage report.
- Optional **GARP_EDINET_INDEX_DATES** to a comma-separated list of up to 20 official index dates on or before the report cutoff. Without it, the bounded search checks the latest five dates and June 19–30 of the latest completed June filing season. This search does not imply all available annuals have been enumerated.
- Optional **GARP_FILING_VENDOR_EXPORT** to an existing approved independent comparison file, if available. Without it, verified original figures can be traced but no independent vendor reconciliation is claimed.

## Source decisions and outputs

Under cycle-report/research/72_filing_preparation, review.json records the decision and reason for each shortlisted candidate.

- **Automatically verified.** EDINET matches the exchange security code, legal filer, annual document type, publication date, fiscal dates and document ID from its official index. An eligible XBRL request goes to the existing primary parser. Gemini approval also requires a separate official PDF, with a readable cover matching the issuer, annual report type and fiscal period. The workflow creates both CSVs when their respective checks pass. It hashes and passes the PDF bytes directly to the existing Gemini agent. Generated CSVs contain credential-free locators; original bytes stay in the private runner directory.
- **Human review.** An ambiguous annual, insufficient cover verification, or unavailable compatible document remains out of Gemini. OpenDART issuer and annual index leads are surfaced when configured. An index link does not establish a verified annual original or fiscal period. For mainland China, Hong Kong and Taiwan there is currently no verified automated attachment discovery route in this pipeline. Explicit reviewed inputs remain supported under the [official-source rules](V06_OFFICIAL_VALIDATION.md#입력-파일).
- **Inaccessible.** Missing publisher credentials, proxy refusals, and failed official fetches are recorded. The workflow skips unverified originals. It generates a dossier from the available evidence for every selected candidate, including unresolved filing or model steps.

Find the dossier index, Markdown and JSON evidence packets, and editable valuation inputs under cycle-report/research/71_research_dossiers in the report artifact. Reviewed numeric assumptions can populate Bear/Base/Bull and sensitivity. Final investment reasoning and approval belong to the human analyst.
