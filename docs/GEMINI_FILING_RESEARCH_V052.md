# Asia GARP Research v0.5.2 — Gemini Filing Research Agent

The optional CLI reads screening and evidence CSVs from a completed v0.5.1 run and produces a separate analyst brief and JSON audit. It uses the existing eligible candidate order or one explicitly selected eligible ticker. The workflow, scores, rankings, acceptance gates, and research decisions continue through v0.5.1.

## Architecture review

| Priority | Original blocker | What the revised agent does | Remaining dependency |
|---|---|---|---|
| 1. Filing and issuer | The evidence ledger often contains a viewer, index, or no filing URL. Seeing the same ticker in two CSVs established no issuer identity. | An operator can approve one exact dated document in a separate manifest, even when the ledger has no filing. Preflight checks that the approved legal issuer name occurs in the filing front matter. An optional source entity identifier, e.g. SEC CIK, is checked against inline XBRL facts. | Confirm exchange ticker, legal entity, filing type, and filing date directly with the publisher. A name match is a screen for errors. |
| 2. Long reports and tables | The first 30 PDF pages and 32 text chunks could omit the statements. Flattening HTML discarded the comparative-column structure. | Searches up to 250 PDF pages and prioritizes statement text. For HTML, it considers the first 300 tables, retains table/row/cell coordinates, and prioritizes statement passages with usable context. The report lists the inspected and shortlisted scope. | PDF text cells generally lack reliable column geometry, so PDF observations remain provisional. Scans and dynamic viewers require a text filing or separate extraction work. Large and unusually formatted reports can exceed the scan limits. |
| 3. Accounting context | Currency, unit, and dates anywhere in one quote could be assigned to the wrong number. | Binds observations to a specific HTML cell, its aligned headers, and inline XBRL facts where present. Separates an instant from a duration, display scale from currency, and filing publication from the reporting period. Flags contradictory context, unknown duration starts, dimensional facts, split signs, and unsupported transformations. | The analyst must inspect consolidated versus parent or segment scope and validate mapping to the research metric. |
| 4. Grounding and uncertainty | A model could crop a multi-period row and claim a match for the first number. | Verifies a full printed row and exact cell identifier independently. Unstructured text must contain the complete matching line and remains provisional, even when the printed number is present. Unsupported extracts are omitted and counted. | The model can omit relevant observations. One passage and up to five proposals keep the initial demonstration bounded. |
| 5. Review boundary | A source match could be mistaken for an approved fact. | `SOURCE_TEXT_MATCH` means the observed cell and the reported context could be mechanically bound. `PROVISIONAL_CONTEXT_UNRESOLVED` carries reasons and any available source fields. Every observation has `analyst_review_status: NOT_REVIEWED` and `filing_verified: false`. | Independently compare the cell with the original filing and the corresponding vendor observation. Record any analyst acceptance through the existing workflow. |
| 6. Repeatability | A URL alone was insufficient to reconstruct what was read. | Records hashes for the inputs, raw source, selected passage, and model proposals, plus parser version, model identity where supplied, and exact quote and context. The saved source can be replayed by hash. A Markdown brief shows the reviewed scope and observations alongside the JSON. | Keep immutable copies of the inputs, source bytes and results with the code revision. Repeating a paid model call can produce different proposals. |

## One-company live demonstration

1. In a Python 3.11 environment, run `python -m pip install -r requirements-gemini.txt`. Obtain the completed v0.5.1 `01_all_research_candidates.csv` and `18_evidence_ledger.csv`. Copy them into an artifacts directory for the demonstration. Select a ticker with `v031_research_eligible=true`. For example, **if eligible**, use `2330.TW` with legal name **Taiwan Semiconductor Manufacturing Company Limited** and SEC CIK **0001046179**. If that ticker is ineligible, use another eligible issuer and its own document metadata.
2. Open the publisher index, and select a dated English annual filing. Prefer SEC EDGAR's primary Form 20-F HTML with inline XBRL so numbers can be bound to comparative columns. Check the legal name and identifier on the cover and record the filing date from the official index. Copy the **final public URL of the report**, not the summary page, viewer, or a redirect. Record the URL for the official date/issuer evidence separately. [TSMC annual reports](https://investor.tsmc.com/english/annual-reports) · [SEC issuer index](https://www.sec.gov/edgar/browse/?CIK=1046179)
3. Create `approved-sources.csv` with the header below and one row for the selected ticker. Use ISO `YYYY-MM-DD` for the publisher filing date. The date, title, issuer name and date-source URL let this file supplement an empty ledger without editing v0.5.1 outputs. For a source already dated in the ledger, you may omit the manifest date. Include the CIK as `issuer_identifier` for a SEC inline XBRL filing. Leave it blank if the official source has no comparable entity identifier. Leave the hash blank until preflight succeeds.

   ```csv
   ticker,source_url,issuer_name,document_date,date_source_url,document_title,issuer_identifier,expected_sha256
   ```

4. Run preflight with network access to the approved publisher. `--dry-run` is also available to read only the local CSVs. Preflight fetches the document and checks the issuer and passages without calling Gemini.

   ```bash
   python -m src.gemini_filing --artifacts ./artifacts \
     --ticker 2330.TW --max-companies 1 --approved-sources approved-sources.csv \
     --preflight --snapshot-dir ./filing-snapshots \
     --output preflight.json --brief preflight.md
   ```

5. Require company status `PRECHECK_READY`. Open the saved filing and independently locate one item such as consolidated revenue. Read the full heading, the selected column's reporting period, its currency and scale, and the adjacent prior-period value. Note the printed figure and exact location before using Gemini. Copy `document_sha256` from preflight into the approval file's `expected_sha256` column. From preflight's `passage_index`, pick the indexed table passage that corresponds to the statement and line item. Prefer a passage with a positive `context_bound_cells` count.
6. Set `GEMINI_API_KEY` securely in the environment and enable egress to `generativelanguage.googleapis.com`. Run on the saved, hash-checked filing. Set `PASSAGE_INDEX` to the zero-based index selected in step 5. The explicit passage selection uses one model request. To exercise the agent's local tool call instead, omit `--passage-index` and set `--max-requests 2`. The default model is `gemini-2.5-flash-lite`, with `gemini-2.5-flash` also configurable. Confirm the configured project can access the selected model.

   ```bash
   python -m src.gemini_filing --artifacts ./artifacts \
     --ticker 2330.TW --max-companies 1 --approved-sources approved-sources.csv \
     --replay-dir ./filing-snapshots --passage-index "$PASSAGE_INDEX" \
     --max-requests 1 --retries 0 --require-source-match \
     --output filing-research.json --brief filing-research.md
   ```

7. Require at least one `SOURCE_TEXT_MATCH` and compare the reported current and comparative cells with the manual reading from step 5. Preserve the brief, JSON, approval file, v0.5.1 inputs, saved filing, and Git commit. A source-text match is evidence for the analyst's thesis. Reconcile the vendor figure, exact period, scope and currency separately before any analyst-approved entry.

## Request and verification boundaries

The default cap is three companies and six Gemini attempts including retries, with a hard cap of nine attempts. Model input is bounded to 24,000 UTF-8 bytes, with 1,024 output tokens per request. The agent requests one local passage or uses an operator-selected passage. The model cannot fetch a URL, run code, or change files. Source downloads are capped at 16 MB and allow no redirect hops. The agent saves bytes only when requested. Replay takes the pinned source from disk, checks its hash, and does not contact the publisher. Stage-specific failures, missing filing inputs, observer uncertainty and the absence of a required source match are visible in the report and CLI exit status.

The current cloud proxy returned CONNECT 403 for both the TSMC annual reports index and SEC issuer index. No official filing content was retrieved from either source. The environment had no `GEMINI_API_KEY`, so no live model call was made. Regression checks used synthetic HTML, inline XBRL and PDF-page fixtures, plus mocked Gemini calls. Run them with `python -m pytest -q tests tests_gemini` after installing the optional requirements.
