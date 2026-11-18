# Asia GARP Research v0.5 — Integrated GitHub Research Pipeline

> **Research-only independent project.** No trading, brokerage orders, allocations, or investment recommendations. Not affiliated with Redpoint Partners or any financial institution. Developed with AI coding assistance; human researcher remains responsible for all numbers, classifications and decisions.

**One repository, one GitHub Actions execution, three research stages:**

1. **DISCOVERY** — Five Asian equity markets (Korea, Japan, China, Hong Kong, Taiwan), curated + actual source-discovered symbols, provenance, basic vendor screening and market balance. In `all5_official`, the pipeline *attempts* official Japan JPX, Taiwan TWSE, optionally Korea KRX with a data.go.kr API key, official Nikkei index, and five vendor regional screeners. China and Hong Kong listing discovery still depends on the vendor screener; not a census. Source failures are logged, not replaced with fictional tickers.
2. **EVIDENCE** — Dated news **headlines only**, vendor quarterly financial rows, optional regulator DART **filing index** (Korea) and explicitly analyst-attested reconciliations of primary filing numbers. Financial statement comparisons must have the same period, units, a dated official/issuer source locator, a reviewer and <=2% deviation. Nothing is automatically counted as filing verified merely because a URL exists.
3. **VALUATION + MEMO** — Three manually specified FCFF DCF scenarios (bear/base/bull), strongest opposing evidence, catalyst, falsification rule, analyst accept/reject decisions, and a per-company research memorandum. The engine does not invent growth forecasts or supply a target price when model inputs are absent. Only reviewed hypotheses pass the final stage.

**Important: This version upgrades research *process auditing*, not demonstrated stock-picking quality.** Its new quality tests cannot establish predictive power or future return outperformance.

## GitHub installation (existing repository; no new repository needed)

1. Download the **full v0.5 GitHub repository ZIP** and unzip it. Copy the **contents** of the inner `ai-quant-asia-garp-research/` folder onto the root of your current `ai-quant-asia-garp-research` GitHub repository. Back up your existing repository first. Include the hidden `.github/` folder. Commit/push using GitHub Desktop (or Git). Do **not** alter your separate `ai-quant-v512-paper` account repository or its `state/latest.zip`.
2. In GitHub open **Actions → Asia GARP v0.5 | Discovery + Evidence + Valuation (Research Only) → Run workflow**. Use `max_symbols=150`, `discover_mode=all5_official`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`. GitHub Action automatically runs all offline regression and quality-gate tests first.
3. After a successful run, download the `asia-garp-v05-<run-id>` Artifact ZIP from the Actions run. The most useful files are `03_research_report.md`, `12_discovery_sources_log.csv`, `22_evidence_sources_log.csv`, `32_research_stage_gate.csv`, `33_analyst_memoranda.md`, `34_research_quality_v05.json`, `35_quality_upgrade_comparison.md`, `36_official_exchange_source_registry.csv`.
4. To verify official filings yourself, edit the two **blank** CSV templates `data/verified_financials.csv` and `data/valuation_assumptions.csv`, plus existing `data/research_decisions.csv`. Commit them and re-run. Empty data are intentional: no false verified recommendations.

**Optional Secrets** in Repository Settings → Secrets and variables → Actions:
- `DART_API_KEY`: Korean OpenDART filing *index*, not verified numerical statements.
- `PUBLIC_DATA_API_KEY`: Korean financial-regulator/KRX listed-securities *identifier* listing via data.go.kr. Requires approved API access. Optional `KRX_BASE_DATE` **Actions variable** `YYYYMMDD` for exchange holidays; otherwise the code requests previous weekday (which can be a Korean exchange holiday and correctly fail).

**No secret** is required for vendor-only regional screeners, JPX, TWSE, news headlines or local quality checks. Some publisher sites can refuse GitHub-hosted requests or change formats; read logs and do not infer complete official coverage from an empty feed.

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
python -m src.v05 --discover-mode all5_official --max-symbols 150 --per-region 90 --fx-mode live --evidence-mode full --evidence-limit 8 --output outputs

# Historical vendor input: no fresh universe, news, FX, filings
python -m src.v05 --discover-mode off --fx-mode off --snapshot-csv snapshot.csv --max-symbols 0 --evidence-mode off --output replay_outputs
# If analyst evidence is used in replay, specify the genuine snapshot cutoff:
python -m src.v05 --discover-mode off --fx-mode off --snapshot-csv snapshot.csv --asof-date 2026-09-30 --output replay_outputs
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
