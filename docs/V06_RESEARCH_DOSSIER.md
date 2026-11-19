# v0.6 Research Dossier

Dossier mode derives candidates in order from the existing issuer-deduplicated screening shortlist, 02_research_shortlist.csv. It schedules primary filing requests only for those candidates and applies the existing filing and model budgets. It does not select an outside candidate when the shortlist is empty or when an approved filing is unavailable. The output directory 71_research_dossiers contains a Markdown and JSON packet per candidate, an execution index, and an analyst-editable valuation input CSV. A blocked run writes the index and CSV without inventing a company.

## First bounded Actions run

Set repository variable GARP_RESEARCH_DOSSIER to 1. Use the existing run-research-v05 workflow on the PR branch with these dispatch values.

| Input | Value |
|---|---|
| cycle_mode, cycle_market | off, All |
| discovery_only, legacy_research, full_universe | false, false, false |
| discover_mode, per_region | all5_official, 90 |
| max_symbols, financial_budget, report_limit | 25, 50, 1 |
| evidence_mode, fx_mode | off, off |
| filing_budget | 1 |
| enable_gemini, gemini_approved_only | true, false |
| gemini_max_documents, gemini_max_requests | 1, 2 |
| official_filing_requests, gemini_approved_sources | Paths to reviewed CSVs within the branch checkout |
| research_asof | Leave blank for current UTC data |

Set GEMINI_API_KEY before a model call. Set DART_API_KEY for Korean issuer resolution and OpenDART requests; set EDINET_API_KEY for EDINET requests. Configure GARP_GEMINI_MODEL to an available model, GARP_GEMINI_MAX_COST_USD to the approved positive spend reservation, and GARP_GEMINI_INPUT_PRICE and GARP_GEMINI_OUTPUT_PRICE to the confirmed USD per million tokens for that model. Optionally lower GARP_GEMINI_TOTAL_INPUT_BUDGET and GARP_GEMINI_TOTAL_OUTPUT_BUDGET. The reservation uses input bytes plus serialized schema and the maximum response length. Estimated cost uses reported API token usage. A request is withheld when its estimated input or reserved output would exceed the configured limits. The filing content and model request counts are independently bounded.

Supply one request for the highest-ranked eligible issuer. If the result is unknown, first run the same workflow with the approval paths blank and Gemini disabled. Review the emitted shortlist and then rerun with the same controls and approved files. If ranking changes, the new shortlist still governs. A historical replay with an authorized timestamped provider snapshot can reproduce an earlier selection but cannot substitute for a live canary.

## Approved inputs

- Use the [official filing request schema](V06_OFFICIAL_VALIDATION.md#입력-파일). EDINET resolves the supplied filing date and issuer metadata through the official list and archive API. For a Korean screened candidate without a scheduled request, dossier mode can use the remaining filing budget to resolve issuer identity and retrieve annual filing index metadata. Confirm the fiscal start/end and receipt in the OpenDART request CSV via GARP_OPENDART_REQUESTS. Index entries are metadata, not statement evidence. For other venues use the publisher's official search and approve the final annual attachment URL. Preserve the original URL and SHA-256 when available.
- Gemini approval CSV fields include ticker, source_url, issuer_name, document_date, date_source_url, document_title, and expected_sha256 where known. Approve an original public PDF/HTML link on the appropriate official host. Dossier mode skips third-party approvals. When primary extraction has already stored the exact approved attachment, the agent uses those hash-matched bytes; otherwise it retrieves the approved original. EDINET XBRL ZIP and OpenDART statement API responses are numerical inputs, not interchangeable with a PDF or HTML annual report.
- For numerical reconciliation, set GARP_FILING_VENDOR_EXPORT to the approved comparable-vendor CSV with the same legal issuer, concept, period, accounting scope, currency and units. A matching original passage can be recorded without numerical reconciliation when independent comparables are missing.
- Edit a private copy of valuation_inputs.csv and review all assumptions. The existing valuation audit supplies any reviewed numeric inputs. Bear/Base/Bull outputs and a ±1 percentage-point discount-rate sensitivity appear only when those inputs pass the existing model checks. Resolve comparability and approval gates independently.

Model observations and quotes are checked against the original, with document hash and passage location. A supporting quotation is only evidence of the quoted text. Its category remains provisional, as do numerical observations without verified statement context. Unsupported proposals are counted and omitted. Narrative extraction is bounded to the selected statement and up to two relevant source passages; absence of an excerpt leaves an explicit review task.

The dossier is an analyst evidence packet. It leaves conclusions, falsification judgments, investment opinions, and final approval to the human researcher. Existing manually reviewed files and gates are unchanged.
