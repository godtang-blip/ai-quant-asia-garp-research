# Asia GARP Research v0.5 — Integrated GitHub Research Pipeline

> **Research-only independent project.** No trading, brokerage orders, allocations, or investment recommendations. Not affiliated with Redpoint Partners or any financial institution. Developed with AI coding assistance; human researcher remains responsible for all numbers, classifications and decisions.

**One repository, one GitHub Actions execution, three research stages:**

1. **DISCOVERY** — Five Asian equity markets (Korea, Japan, China, Hong Kong, Taiwan), curated + actual source-discovered symbols, provenance, basic vendor screening and market balance. In `all5_official`, the pipeline *attempts* official Japan JPX, Taiwan TWSE, optionally Korea KRX with a data.go.kr API key, official Nikkei index, and five vendor regional screeners. China and Hong Kong listing discovery still depends on the vendor screener; not a census. Source failures are logged, not replaced with fictional tickers.
2. **EVIDENCE** — Dated news **headlines only**, vendor quarterly financial rows, optional regulator DART **filing index** (Korea) and explicitly analyst-attested reconciliations of primary filing numbers. Financial statement comparisons must have the same period, units, a dated official/issuer source locator, a reviewer and <=2% deviation. Nothing is automatically counted as filing verified merely because a URL exists.
3. **VALUATION + MEMO** — Three manually specified FCFF DCF scenarios (bear/base/bull), strongest opposing evidence, catalyst, falsification rule, analyst accept/reject decisions, and a per-company research memorandum. The engine does not invent growth forecasts or supply a target price when model inputs are absent. Only reviewed hypotheses pass the final stage.

**Important: This version upgrades research *process auditing*, not demonstrated stock-picking quality.** Its new quality tests cannot establish predictive power or future return outperformance.

## 발전 과정 — 무엇이 문제였고, 왜 다음 버전으로 고쳤는가?

이 프로젝트는 처음부터 정답을 알고 만든 완성형 투자모델이 아닙니다. **실제 실행에서 확인한 실패·편향·검증 공백을 기록하고 그때마다 연구 절차를 수정한 프로젝트**입니다. 아래의 수치와 검증 수준은 각각의 당시 관측·구현 자료에 근거하며, 버전별 점수의 단순 증감은 투자성과 개선을 의미하지 않습니다.

| 버전 | 당시 시도·구현 | 드러난 문제와 다음 변경의 이유 | 다음 버전에서 취한 조치 / 남은 한계 |
|---|---|---|---|
| **v0.1 — 출발점** | 소규모 기업을 대상으로 성장성과 가치평가 지표를 결합한 GARP 스타일 스크리닝 실험 | 반도체 기업 쏠림과 일부 Yahoo Finance 재무지표의 신뢰성 문제가 드러남. 점수만 보고 기업 간 우열을 비교하기 어려웠음 | **v0.2**에서 산업별 비교집단을 도입하고 데이터 품질 문제를 명시적으로 표시하는 쪽으로 수정 |
| **v0.2 — 비교집단 확대** | 사전에 선정한 61개 기업, 산업별 피어그룹, 명시적 데이터 품질 경고 | 홍콩 상장종목의 통화·재무제표 단위가 뒤섞일 가능성, 회계기간과 P/E 수치의 불확실성 | **v0.2.1**에서 이상치 격리와 통화 관련 제한을 강화. 숫자가 있다고 무조건 비교하지 않도록 설계 |
| **v0.2.1 — 이상치 격리** | 의심 지표를 자동 평가에서 보수적으로 제외·격리하고 통화·기간 불확실성을 기록 | 미리 선정한 종목만으로는 알려지지 않은 기업을 발굴하기 어려움. 산업 간 공통 조사 우선순위도 필요했음 | **v0.3**에서 신규 종목 자동 탐색, 산업별 기준을 반영한 공통 조사 점수, 환율·회계기준 감사를 시도 |
| **v0.3 — 신규 발굴 실험** | 한 차례 관측 실행에서 **416종목**(그중 신규 발견 355종목) 확보, 100점형 산업 민감도 점수와 환율·회계기준 점검 도입 | **416종목 중 일본 272개**, 중국 본토 1개로 지역 편중. 새로 발견한 **355종목 모두** 당시 리서치 후보 검증 단계에서 제외됨. 공시 수치 대조 역시 미확인 | **v0.3.1**에서 5개 시장별 탐색 시도, 지역 균형 표본 추출, 신규 종목의 *조건부 조사 후보* 허용, 출처·반증 기록 추가 |
| **v0.3.1 — 출처와 반증의 도입** | 한국·일본·중국·홍콩·대만 탐색, 통화가 불명확한 EPS 기반 P/E 보류, 뉴스 제목·실적 제공업체 데이터·DART 공시 **목록**, 수동 `REJECTED` 기록, 동일 입력 가중치 민감도 검사 | 실제 보관된 실행 결과에서 **684종목 분석 / 623종목 점수 산출 / 조사 후보 94개 / 이상 경고 287건**이었지만, **공식 공시 재무수치 대조는 0건**. 점수가 높은 후보도 투자 판단에 필요한 근거·가치평가가 부족 | **v0.5**에서 공시 숫자 대조, 검증 상태 게이트, 3개 가치평가 시나리오, 반대 논거와 투자메모로 연구 절차를 연결 |
| **v0.5 — 세 단계 통합** | 5개 시장 탐색→근거 수집·대조→가치평가·투자메모를 **GitHub Actions 1회 실행**에 연결. 공개 거래소 목록 어댑터 추가, 증거·분석가 서명·반대논거·반증 조건 확인 | 프로세스가 정교해졌다고 실제 종목 선정의 미래 예측력이 개선됐다고 말할 수 없음. 공식 공시의 직접 수치 대조와 분석가 가정 입력은 여전히 필요 | 기존 v0.3.1 자료를 동일 입력으로 재평가해 `SCREENED 94 / EVIDENCE_CHECKED 0 / VALUATION_REVIEWED 0 / MEMO_READY 0` 확인. **승격을 막는 게이트가 작동함**은 확인했지만 수익률 개선은 미입증 |

### 연구상 의미와 검증 범위

- **신규 발굴 ≠ 리서치 품질:** 61→416→684라는 관측 규모 증가는 검색 범위의 변화입니다. 평가 대상 종목군·데이터 시점이 달라 버전 간 성과 개선 비교가 아닙니다.
- **스크리닝 점수 ≠ 투자 의견:** v0.3부터의 100점형 점수는 *추가 조사 우선순위*입니다. 산업별 가중치의 미래 초과수익 예측력은 검증되지 않았습니다.
- **공식 거래소 목록 ≠ 공식 재무 검증:** 상장기업을 공식 목록에서 찾았더라도 재무제표 수치가 검증된 것은 아닙니다. v0.5의 `EVIDENCE_CHECKED`는 직접 읽은 공시와 수치·기간·단위를 대조한 분석가 확인을 요구합니다.
- **재현성 검사 ≠ 알파 검증:** 자동 테스트와 동일 입력 민감도 검사는 코드·절차의 안정성을 점검합니다. 미래 수익률 검증에는 시점 일치 데이터, 생존편향·룩어헤드 통제, 표본 외 추적이 별도로 필요합니다.
- **버전별 실제 문제의 기록:** [`CHANGELOG.md`](CHANGELOG.md)는 릴리스 단위 변경 내용을, [`docs/README_v031_legacy.md`](docs/README_v031_legacy.md)는 v0.3.1 당시 원본 설명을 보존합니다. 무엇을 *실제로* 확인했는지와 아직 확인하지 못한 사항을 구분합니다.

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
