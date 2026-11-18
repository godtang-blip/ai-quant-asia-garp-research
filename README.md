# Asia Equity Research — GARP-style research pipeline v0.3.1

**Independent research-only prototype. Not affiliated with or endorsed by Redpoint Partners.**

This project began as a personal investment/quant workflow and evolved through mistakes observed in real runs. Its objective is **new company discovery → data provenance → comparable investigation scores → primary-source verification → evidence and counterevidence → an analyst's explicit accept/reject/on-hold decision**. A high score is *not* a security recommendation or an expected return.

## What is demonstrated vs not yet demonstrated

| Area | Actually implemented | Still NOT verified |
|---|---|---|
| Universe | 61 curated + official Nikkei index discovery + 5 Yahoo regional screeners (Korea, Japan, mainland China, Hong Kong, Taiwan), dedup, security-type filtering, market-balanced fetch | Complete stock exchange census, perfect country coverage, verified issuer identities |
| Fundamentals | Data/vendor metadata, risk flags, 0–100 research-priority scoring with industry-sensitive anchors | Financial statement figures reconciled to issuer primary disclosures, forward alpha, calibrated cross-sector returns |
| FX | Quote/reporting currency, USD FX quotes and 1-year average flow proxy, dated source/FX logs; hold ambiguous mixed-currency forward P/E | Audited historical FX translation of actual matched fiscal cash-flow periods; currencies of every provider EPS field |
| Accounting | Per-issuer accounting standard disclosure ledger and unknown/issuer-review status | Automatic GAAP→IFRS restatement or validated economic comparability across different standards |
| Evidence | Google News **headlines** with links and dates, Yahoo vendor quarterly figures, optional Korea OpenDART filing **index** with regulator URLs | Full article reading; auditing the reported figures; five-market official filing API integrations |
| Research | Candidate investigation queue including newly discovered equities, analyst `ACCEPTED / REJECTED / ON_HOLD / INVESTIGATING` decisions; evidence book | Autonomous acceptance of hypotheses, verified valuation or investment memo |
| Validation | Automated tests, versioned logs, **same-input 10 scenario ±20% weight perturbation**, quality diagnostic outputs | Empirical predictive power, unbiased historical point-in-time walk-forward backtest |

## Quick start — existing GitHub repository

1. Unzip `asia_garp_research_v031_full_repo.zip`. Open the **inner** `ai-quant-asia-garp-research/` folder and replace the files at the root of the existing research repository. Include the **hidden `.github/` folder**. Push/commit. Do not touch other paper portfolios.
2. Open **Actions → Asia GARP Research v0.3.1 — Manual Only → Run workflow**.
3. First 5-market test: `max_symbols=150`, `discover_mode=all5`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`, `evidence_limit=8`. `max_symbols=0` runs the entire discovered watchlist, which can take much longer and hit vendor rate limits; test at 150 first.
4. Download the `asia-garp-research-v031-...` Artifact ZIP. Read `03_research_report.md`, `24_research_quality_audit.md`, `27_evidence_book.md`, `18_evidence_ledger.csv`, `23_same_input_weight_sensitivity.csv`, `12_discovery_sources_log.csv`.

**Optional Korea regulator connector:** Create an OpenDART API key directly with the regulator and enter it in GitHub repository **Settings → Secrets and variables → Actions → New repository secret**, name `DART_API_KEY`. Without a key, the workflow still runs and logs `API_KEY_NOT_CONFIGURED`. The key is read from environment only; never put it in code/ZIP/README. OpenDART currently provides **filing metadata links**, not verified numbers. Other four markets require manual issuer links via `data/issuer_source_registry.csv` until official connectors are implemented.

### Local / Colab

```bash
pip install -r requirements.txt
python -m pytest -q tests
python -m src.v031 --max-symbols 150 --discover-mode all5 --per-region 90 --fx-mode live --evidence-mode full --evidence-limit 8 --output outputs
# Reproduce scoring offline on a previously saved vendor CSV; NO live FX/news/filings in replay:
python -m src.v031 --max-symbols 0 --discover-mode off --fx-mode off --snapshot-csv snapshot.csv --evidence-mode off --output replay_outputs
```

`notebooks/Run_Asia_GARP_Colab.ipynb` is the notebook entry point. DART integration requires a configured key in the execution environment.

## 5 markets ≠ identical numbers ≠ universe census

The watchlist combines historical curated names, the official Nikkei 225 constituent list when the page is parseable, and Yahoo Finance screeners by market. Yahoo screens are **vendor subsets**, not full exchange directories. The five markets may be unbalanced due to source limitations; inspect `12_discovery_sources_log.csv` and `11_discovery_universe.csv`. The selected *fetch* sample is round-robin balanced across available markets when `max_symbols>0`, **not the final top-ten portfolio allocation**. A/H dual listings are de-duplicated by ticker only; issuer-level cross-market duplicate reconciliation remains a TODO.

## Accounting and currency rules

- `src/fx.py` (retained from v0.3) reads `currency` (share price/market cap) and `financialCurrency` (financial statements). Converts market cap at a **dated spot**; vendor annual FCF with a **1-year average FX approximation** when available and recomputes comparable USD FCF yield. The provider's FCF period is unknown. Currency conversions are *proxies*, not IAS 21-compliant issuer restatements. Without source FX, no fabricated converted value.
- A vendor forward EPS in a different/unknown currency is **not** mechanically divided by the local price. Mixed-currency forward P/E is withheld. P/S may use USD market cap and vendor total revenue with a proxy exchange rate, and the assumption is marked.
- `src/accounting.py` (retained from v0.3) records **issuer-specific** primary-filing evidence (`data/accounting_issuer_evidence.csv`) and marks standards unknown until an analyst enters a dated source. Identifying a standard is **not** restating one GAAP to another, and operating margin/ROIC definitions may still diverge.

## Evidence, rejected hypotheses, and actual investment memos

`18_evidence_ledger.csv`: for every news **headline** / vendor **quarterly value** / optional official **filing listing**, store ticker, date, URL, source tier, and verification status. It deliberately leaves `claim_supported` blank; only analyst review can verify a concrete statement. Headlines are not assumed true; positive/negative classification is not fabricated.

`27_evidence_book.md` joins the high-priority investigation names with those sources, showing exactly what is and is not known. `20_vendor_quarterly_earnings.csv` is not an issuer financial statement; `21_regulator_filings_index.csv` identifies potential Korean primary disclosures but does not read them.

`data/research_decisions.csv` is **manually maintained** with ticker, analyst decision, date, initial thesis, counterevidence, explanation, source URLs, revisit trigger, and reviewer. Decisions: `INVESTIGATING`, `ON_HOLD`, `REJECTED`, `ACCEPTED`. **Rejecting a hypothesis based on evidence is a valid research result** and must be preserved with its underlying reason. A high automation score NEVER automatically becomes `ACCEPTED`.

Final investment memo should explain: business model → structural growth → why market expectations are wrong → valuation method/scenarios → hard catalysts/counterevidence → falsification conditions. An analyst must verify the numerical source evidence and personally defend each assumption.

## Validation: does newer software produce BETTER analysis?

A green CI result verifies that software executes, **not** that the model predicts stock returns. `24_research_quality_audit.json` lists actual collection/coverage/failure metrics and zero issuer-financial-statement reconciliations until manually audited. `23_same_input_weight_sensitivity.csv` measures rank shifts under ten ±20% single-factor weight changes on exactly the same input data; `top10_scenario_share` is a *stability indicator*, not validated alpha.

Different-vintage results are not directly comparable without frozen input universe and vendor data. For future empirical performance verification, store timestamped scores and source as-of dates, prohibit future data leakage, track long-horizon returns, and test out-of-sample after sample size builds. Never infer superiority from a larger universe, more code, or higher rank.

## Versions — failures are part of the portfolio

| Version | What changed | What prompted the next revision |
|---|---|---|
| 0.1 | Small GARP sample | Semiconductor concentration and suspect Yahoo metrics |
| 0.2 | Curated 61 names, industry peer groups, explicit quality warnings | Hong Kong currency conflict and period/PE uncertainties |
| 0.2.1 | More conservative anomaly quarantine and currency limitations | Wanted previously unknown securities and a common investigation scale |
| 0.3 | Expanded to 416 names in **one observed run**, 355 discovered, numerical sector-sensitive score and FX audit | 65% Japan; mainland China nearly absent; new discoveries excluded from shortlist; actual GAAP/filing not verified |
| **0.3.1** | Five-market discovery attempts, market-balanced fetch, provisional new-name shortlist, mixed-currency PE hold, source ledger, decision log, same-input sensitivity and quality audit | **Live five-market/evidence run still to validate**; some vendor datasets may be unavailable |

**Commit history is not enough to explain *why* a decision changed.** Compare corresponding archived run Artifacts, source/evidence status, and `CHANGELOG.md`; write up meaningful issues and their fixes. Do not treat 0.3.1 offline tests as a live-source or prediction-quality validation.

## Outputs

Core: `01_all_research_candidates.csv`, `02_research_shortlist.csv`, `03_research_report.md`, `04_run_metadata.json`, `09_filing_verification_queue.csv`, `11_discovery_universe.csv`, `12_discovery_sources_log.csv`, `13_fx_normalization_audit.csv`, `14_accounting_comparability_audit.csv`, `15_cross_industry_scores.csv`, `17_fx_quotes_log.csv`.

New v0.3.1: `18_evidence_ledger.csv`, `19_news_headlines.csv`, `20_vendor_quarterly_earnings.csv`, `21_regulator_filings_index.csv`, `22_evidence_sources_log.csv`, `23_same_input_weight_sensitivity.csv`, `24_research_quality_audit.json`, `25_research_quality_audit.md`, `26_research_decisions.csv`, `27_evidence_book.md`, `28_decision_log_GUIDE.md`, `29_new_discovery_research_queue.csv`.

## Defending the methodology in a PM interview

See [`docs/PM_면접_설계방어_질문.md`](docs/PM_면접_설계방어_질문.md) for **what each score measures, why weights/FX/GAAP are not yet proven, counterfactuals, and 10 concrete questions**. This is a self-test, not a claim that AI-assisted code was written independently.

## Responsible publication and AI contributions

Only code, methods, selected **redacted** example outputs and permitted sources should be published. Never commit secrets, personal account balances, paid licensed datasets, or complete news articles. AI assisted implementation, while project requirements, hypothesis questions, reviewing outcomes and research decisions are user-directed; personal development proficiency is not misrepresented. Code does **not** place trades or modify the other simulated portfolios.
