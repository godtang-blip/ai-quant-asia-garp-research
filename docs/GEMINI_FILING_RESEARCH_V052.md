# Asia GARP Research v0.5.2 — Gemini Filing Research Agent

This optional CLI consumes two CSVs from a completed v0.5.1 run and writes a separate JSON research report. It uses the existing screening order or explicit selections from that eligible universe. The scoring pipeline, investment rankings, evidence gates, and GitHub Actions workflow have no dependency on Gemini.

## Set up and plan a run

Use Python 3.11 or later. Install the optional dependencies in your development environment.

```bash
python -m pip install -r requirements-gemini.txt
```

Point `--artifacts` to the directory containing `01_all_research_candidates.csv` and `18_evidence_ledger.csv`. Prepare a local `approved-sources.csv` with the header `ticker,source_url` and one row for each exact public filing URL you have reviewed for that ticker. An eligible URL must occur in both files, have a valid publication date in the ledger, and be a regulator filing or an issuer filing link designated as `filing_url`. The CLI selects the latest eligible approved filing per company. Review the actual document URL, issuer identity, and publisher before approving it. Use final public HTTPS URLs for downloadable PDFs or static HTML. The approval file is trusted operator input.

```bash
python -m src.gemini_filing --artifacts outputs \
  --approved-sources approved-sources.csv --output gemini-plan.json --dry-run
```

Dry-run reads local CSVs, reports the planned sources and gaps, and makes zero network requests. For a paid run, configure `GEMINI_API_KEY` as an environment secret and rerun with a new output path and without `--dry-run`. The CLI uses the Gemini API endpoint through the Google Gen AI Python SDK. Its default model is `gemini-2.5-flash-lite`. Use `--model gemini-2.5-flash` to select the other supported model. Repeat `--ticker` to use explicit eligible tickers. The default and maximum selection is three companies. You can lower it with `--max-companies`.

## From filing to observation

1. Python checks approvals and downloads the exact filing URL once. Redirects, authenticated URLs, linked pages, scripts and frames are excluded. PDF text and HTML table rows are recorded with page or normalized-text locations. The report preserves the URL, ledger publication date, retrieval time, and SHA-256 of the downloaded bytes.
2. Gemini receives short previews and can request one passage using `read_passage`. Python checks the tool name and index, reads only from the local document, and sends that passage in a separate extraction request with a JSON schema. Neither model request can browse or execute code.
3. Python checks the quote against the selected text and requires the exact printed number and metric label on the same line. It discards unsupported numbers and quotes. A single number with explicit matching currency, unit, and ISO reporting dates can receive `SOURCE_TEXT_MATCH`. Ambiguous table columns or missing context receive `PROVISIONAL_CONTEXT_UNRESOLVED`. The report keeps the original text, exact decimal string before scaling, stated units and currency, period, and locator. It identifies the publication date as ledger metadata.
4. A source-text match establishes that the quoted text contains the figure and its stated context. Issuer identity, financial statement interpretation, and cross-filing reconciliation still require analyst review. All records carry `filing_verified: false`. The CLI writes no scores, review approvals, evidence ledger updates, or orders.

The default budget is six Gemini requests total, including retries. Each filing takes at most one successful tool selection and one successful extraction. The CLI allows two to nine attempts per run, caps input text at 24,000 UTF-8 bytes and generated output at 1,024 tokens per request, disables model thinking and SDK retries, and accepts at most five proposals per filing. Its own limited backoff retries transient provider errors within the same request budget. Downloads are limited to 4 MB, with timeouts and up to 30 PDF pages and 32 sampled passages. These per-run controls bound workload; actual billing depends on the chosen model and provider pricing. Configure project-level budgets and quotas for cumulative spend.

## Current integration limits

A real dry-run against the current completed artifacts will show which of the top eligible tickers have dated filing entries. The v0.5.1 run in progress is untouched. Its artifacts are needed to measure approval coverage, exercise live sources, and compare observations with vendor periods and analyst records. A separately configured key and egress to `generativelanguage.googleapis.com` plus the approved publishers are needed for a live Gemini run.

The first implementation covers text PDFs and static HTML. Scans, JavaScript-only viewers, and regulator index pages without statement text may produce no observations. Multilingual date formats, separate table headers, and ambiguous comparative columns need manual review. Explicit source URLs are required in the input ledger. The module never substitutes a news article, vendor quote, or earnings-source link for a filing.

Run the optional regressions with `python -m pytest -q tests_gemini` after installing the optional dependencies. They use local fixtures and mocked requests. Run `python -m pytest -q tests` to check v0.5.1 compatibility.
