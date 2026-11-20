# Asia GARP Research

An independent, AI-assisted equity research engine that ranks companies for investigation using **growth at a reasonable price (GARP)**. It covers Korea, Japan, mainland China, Hong Kong, and Taiwan. The researcher directs verification and investment decisions. AI assists with implementation and analysis.

**30-second summary.** A live listing-only run found **16,629 security codes**. A separate snapshot replay produced **439 research scores** from **500 usable financial records**. DB HiTek, an existing watchlist company, ranked **2nd at 77.15**. Follow-up filing and DCF research found insufficient evidence of a margin of safety at the cited closing price, so the researcher kept it on **Watch**. The project has not backtested investment returns.

[DB HiTek report (PDF, Korean)](case-studies/db-hitek/db-hitek-equity-research-2026-11-20.pdf) · [Screening and valuation evidence](case-studies/db-hitek/screening_evidence.md) · [Pipeline code](docs/PORTFOLIO_RUNBOOK.md#pipeline-code) · [Reproduce and test](docs/PORTFOLIO_RUNBOOK.md#local-reproduction)

## Observed runs

| Run | Observed result | Validation scope |
|---|---|---|
| **A · Live listing collection** | [Actions #44370844839](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44370844839), November 19, 2026 KST. **16,629 unique security codes** across five markets. | `discovery_only`. Listing sources and failures were recorded. Financial retrieval, scoring, and return validation were outside this run. [Market breakdown](docs/FIVE_MARKET_DISCOVERY_MILESTONE.md) |
| **B · Financial snapshot replay** | November 19, 2026. **16,671** watchlist codes, **500** usable financial records, **439** scored. **TSMC 1st (80.55)**, **DB HiTek 2nd (77.15)**. | `SNAPSHOT_REPLAY_NOT_LIVE`, pipeline revision `0.3.1`. The run recorded zero verified investment memos and no primary-statement verification or return backtest. [Source hashes and derivation](case-studies/db-hitek/screening_evidence.md#screening-record) |

## DB HiTek case

- **Selection.** DB HiTek was already on the watchlist (`CURATED_LIST`). Its rank and testable foundry economics made it a useful research case. The researcher chose it to investigate utilization, product mix and expansion economics.
- **Fundamental review.** The researcher used company disclosures and a separate DCF to trace how capacity, capital spending and depreciation could affect free cash flow. The reported close was **KRW 68,500** on November 20, 2026.
- **Decision.** **Watch. Defer initiating a position.** The conditional bridge gave partial values of **KRW 59,458 / 67,254 / 73,851** per share. The calculation uses a different valuation date and omits a complete reconciliation of subsidiary value, excess cash and the exchangeable bond. The report sets no target price. Revisit as equipment installation, customer qualification and cash returns on invested capital become observable. [Case summary and source limits](case-studies/db-hitek/README.md)

## Human-directed, AI-assisted

The researcher set the objective, selected the case, specified how to verify claims, and made the investment judgment. ChatGPT contributed to code, filing research, DCF calculations and report drafting. Codex implemented code, tests and documentation through GitHub PR work. GitHub Actions recorded execution and source failures. The DB HiTek PDF and DCF were produced as a separate research exercise. [PRs, failures and fixes](docs/AI_DEVELOPMENT_TRAIL.md) · [Version history](docs/DEVELOPMENT_HISTORY.md)

## Limits and reproduction

Listing counts measure security codes and can include multiple codes for an issuer. Source access and vendor definitions limit coverage and comparability. GARP scores prioritize research and have no validated mapping to expected returns. [Scope and screening evidence](case-studies/db-hitek/screening_evidence.md)

Run from the repository root with Python 3.11.

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m src.discovery_smoke --output discovery-smoke
```

The listing smoke check writes source status by venue. External coverage depends on source access and optional credentials. [Pipeline and workflow guide](docs/PORTFOLIO_RUNBOOK.md)
