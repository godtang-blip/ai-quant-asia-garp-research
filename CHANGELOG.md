## v0.5.1 — market coverage, classification and evidence-quality follow-up (2026-11-18)

- Based on the submitted v0.5 run: 1,722 analyzed, 1,121 Taiwan (65.1%), 240 screening-eligible. This is observed **source imbalance**, not proof Taiwan has the most attractive equities.
- JPX listing parser now detects multiple English/Japanese header variants and title-row offsets; rejects non-domestic equity product classes. Offline fixtures passed, live JPX integration remains unverified until the next Action run.
- Changed ambiguous vendor `Electronic Components` / `Electrical Components` to `unclassified` for human product-level review instead of defaulting to industrial electrification.
- Added coverage status `PARTIAL_COVERAGE`, market concentration diagnostics, a global queue separate from 5-country research review queues, and a blocked high-score recheck list.
- Added title-only entity relevance checks for news RSS; articles referencing another listed ticker are quarantined. Matching a title is not proof the news content or financial claim was read/verified.
- Preserved strict manual primary-financial reconciliation and 3-scenario DCF/memo gates. No automated issuer filing numeric verification, cross-market census, external success validation or portfolio orders.
- Reused the existing single `.github/workflows/run-research-v05.yml` entry point, now invoking `src.v051`; no extra active workflow.

## v0.5.0 — workflow consolidation patch (2026-11-18)
- Designated `.github/workflows/run-research-v05.yml` as the **sole** active GitHub Actions research workflow.
- Retired the standalone v0.3.1 `.github/workflows/run-research.yml` (must be deleted when upgrading an existing checkout).
- Preserved the v0.3.1 engine as a Python dependency of `src.v05` and archived the historical workflow specification under `docs/`.
- Added three workflow-layout regression tests and explicit migration instructions to prevent duplicate runs.
- No changes to screening, valuations, investment decisions, or trade execution.

## 0.5.0 — 2026-11-18 — integrated three-stage research quality gates
- Added optional JPX XLSX, TWSE open data, KRX authenticated issuer listing adapters with provenance; vendor regional screeners remain and no full-census claims.
- Added manual primary-financial reconciliation, strict same-period/source/reviewer/2% gates, and company-level stage reports.
- Added 3-scenario FCFF DCF with explicit manually supplied assumptions, bear case, catalyst, falsification trigger, analyst acceptance gate.
- Added v0.5 GitHub workflow (manual one-click), 30..37 audit artifacts, regression tests, and an English README documenting the full version history and investigation rationale.
- Applied gates to archived v0.31 live-result dataset: 684 analyzed, 94 screened, 0 evidence checked, 0 memo ready. This is a truthful baseline, NOT improved stock selection accuracy.

# Release and investigation log

## v0.3.1 (implementation release, live integration still unverified)

- Kept v0.3 **FX conversion and issuer accounting provenance** with no fabricated GAAP→IFRS restatement.
- Five-market discovery attempts: Korea/Japan/mainland China/Hong Kong/Taiwan. Region symbol patterns, security type guard, source error logs, round-robin fetch selection.
- Previously discovered names can enter **provisional** research shortlist if vendor identity, sector, profitability, metric coverage and anomaly checks pass. No automatic promotion to a confirmed investment idea.
- Forward P/E is held out for mixed quote/reporting currencies without EPS unit verification. P/S can be recalculated with an explicitly estimated flow-period exchange rate.
- Added bounded news RSS headline discovery (not article content), vendor quarter extracts, Korea OpenDART filing-index references with optional secret, issuer source registry and Evidence Book.
- Added human research decision ledger, including **REJECTED** with decisive counterevidence and conditions to revisit.
- Added same-input category-weight sensitivity tests and automatic diagnostics. Predictive power, accurate GAAP conversions and official figure reconciliation remain unverified.
- No orders, trade placement, portfolio state changes or changes to existing other repositories.

## v0.3 (416-ticker sample observed, research-only)

- Expanded beyond curated 61; one real user run reported 416 names including 355 newly discovered.
- Follow-up audit: Japan 272/416, mainland China 1; all 355 new names excluded by research gating. Not a comprehensive five-market universe.
- Began USD FX proxies and issuer accounting standard audit. Different-industry 100-point ranking is NOT return-calibrated.

## v0.2.1 — anomaly quarantine after currency/period uncertainty

- Increased conservative quarantine of suspect vendor financial metrics and ambiguous Hong Kong currency handling. Unresolved fiscal-period/PE issues remain a limitation.
- Next issue: static curated lists did not discover unfamiliar issuers or provide a defensible cross-industry research priority.

## v0.2 — curated 61-company comparison

- Used an expanded 61-company watchlist, industry peer-groups, and explicit financial metric warnings to address the semiconductor concentration and questionable vendor figures found in the earlier experiment.
- Next issue: inconsistent currency and reporting-period treatment could create misleading ratios, especially for Hong Kong listings.

## v0.1 — initial GARP experiment

- Started with a small candidate set and growth/value-based screening. Observed semiconductor clustering and suspect Yahoo-derived metrics; these observations motivated peer-group and data-quality checks rather than stronger return claims.

**Comparison caution:** Historical runs use differing vendor snapshots, universes and scoring rules. The versions do not form a controlled study of investment performance.

## v0.6 개발 변경

- 기존 스크린에 5개 시장의 재무 호출 예산과 재실행용 체크포인트를 연결했습니다.
- 승인된 공시 export의 출처 등록, 원본 해시 검사, 기간·범위·통화를 일치시킨 수치 대조를 추가했습니다.
- Gemini v0.5.2 추출기를 옮기고, 커버리지·검토 보류·실행 매니페스트를 기존 산출물과 함께 생성합니다.

- EDINET API v2의 공개 XBRL과 SSE·SZSE·BSE·HKEXnews·MOPS의 승인된 공식 원문 취득 경로를 추가했습니다.
- 기존 Actions에 Gemini 키, 승인 목록, 호출 예산을 연결하고 실행 결과에 공급자 응답·원문 취득·파싱·수치 대조·보고서 생성 결과를 별도로 기록합니다.

- 전체 시장 사이클의 동결 계획, 시장별 샤드, 원자적 종목 예약, Actions 체크포인트 복원과 일일 작업 예산을 연결했습니다.
- 증거 기반 분류와 금융 지표의 출처를 별도로 보존하고, 같은 입력으로 적격성 변경을 비교합니다.
