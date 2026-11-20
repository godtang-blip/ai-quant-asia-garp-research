# Asia GARP Research Engine

아시아 상장기업의 데이터를 모아 GARP 기준으로 조사 우선순위를 만들고, 공식 공시와 사람이 검토할 근거를 묶는 AI 보조 리서치 프로젝트입니다. 한국, 일본, 중국 본토, 홍콩, 대만을 다룹니다. 최종 투자 논거, 밸류에이션 가정과 의사결정은 애널리스트가 책임집니다. [v0.6 통합 PR #4](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/4)

## 최근 Research-now 캠페인

사이클 `44456766424`의 완료 결과로 제공된 운영 집계입니다. 이번 변경에서는 원본 체크포인트를 다시 수집하거나 재실행하지 않았습니다. 작업 환경에서 Actions 아티팩트 다운로드가 차단되어 이 집계의 독립 재확인은 보류했습니다.

| 단계 | 결과 |
| --- | ---: |
| 동결된 발견 종목 | 16,671 |
| 누적 재무 공급자 호출 시도 | 500 |
| 데이터가 충분해 점수화된 종목 | 439 |
| 1차 정량 기준 통과 | 61 |
| Research-now | 정상 완료 |

16,671은 고정된 발견 모집단입니다. 500은 재시도와 실패가 포함될 수 있는 호출 시도이며, 61은 후속 조사를 위한 통과 수입니다. 업종은 거래소·공급자 자료와 검토 기록의 범위에 따라 자동·잠정·미해결 상태로 나뉩니다. 누락되거나 비교하기 어려운 회계기간, 통화, 업종, 종목 유형은 각 감사 파일에 기록합니다. 현재 점수 체계의 미래 수익 예측력은 검증되지 않았습니다.

기존 실행에서 NISSUI와 KYOKUYO의 EDINET XBRL 공시를 파싱한 관측이 보고됐습니다. Gemini는 승인 원문의 근거 문구를 구조화하며, 출처 확인, 숫자 대사, 실제 API 응답, 애널리스트 검토는 별도로 집계합니다. Gemini 라이브 연동은 선행 작업에서 확인됐으며 이번 작업에서 재실행하지 않았습니다. 시장 전체나 유키구니 전망치까지 검증됐다는 의미는 아닙니다. [공시·Gemini 운영 안내](../V06_RESEARCH_DOSSIER.md)

## 재무 신뢰성 사례 · Yukiguni Factory (1375.T)

2026-11-19 공급자 스냅샷으로 제공된 주가 1,137엔, Forward EPS 158엔, Forward PER 7.1962배는 내부 산술상 일치합니다. 같은 주가를 제공된 FY2027 회사 전망 EPS 63.69엔으로 나누면 17.8521배입니다. 공급자 추정기간과 산정 정의가 미확인이므로 이 차이는 `PERIOD_MISMATCH_OR_UNRESOLVED`입니다. 별도 TTM EPS 97.76엔은 독립된 기간입니다.

공급자 원본과 기존 탐색 점수는 보존합니다. 문서와 날짜, EPS 및 가격의 주식 기준을 확인한 명시적 검토가 있어야 별도 재평가가 계산됩니다. IFRS 총수익과 제품 판매 매출은 정의를 분리합니다. 회사 정의 Core 영업이익은 비IFRS 조정 지표로 보관하며 일반 영업이익, 순이익, EPS의 대용값으로 사용하지 않습니다. [검증 결과와 감사 보고서](../V06_FINANCIAL_TRUST_AUDIT.md)

## 재현하기

Python 3.11을 사용합니다. 아래 검증과 사례 재현은 로컬에서 실행하며 공급자 키를 요구하지 않습니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-gemini.txt
python -m pytest -q tests tests_gemini
python -m src.financial_provenance case
```

기존 캠페인의 최종 순위가 있으면 그 CSV에서 바로 재무 감사를 실행합니다. 예시 날짜는 보유한 아티팩트의 감사 기준일에 맞춥니다. 이 명령은 원순위를 보존하고 새 폴더에만 감사 결과를 기록합니다.

```bash
python -m src.financial_provenance audit-ranked \
  --ranked /path/to/campaign/research/01_all_research_candidates.csv \
  --asof-date 2026-11-19 \
  --output outputs/checkpoint-audit
```

입력 정의와 승인 기록을 재현하려면 감사 보고서의 `--metric-evidence-dir`을 사용합니다. 실제 수집이 필요한 Research-now의 시작과 재개는 기존 GitHub Actions 워크플로와 같은 사이클의 체크포인트로 진행합니다. 라이브 공시 및 Gemini에 필요한 키는 Repository Secrets에서 관리합니다. [캠페인 실행 안내](../V06_CAMPAIGN.md)

## 구조와 주요 산출물

| 위치 | 역할 |
| --- | --- |
| `src/discovery_v031.py`, `src/research_cycle.py`, `src/research_campaign.py` | 5개 시장 목록 수집, 동결 계획, 체크포인트와 캠페인 재개 |
| `src/v031.py`, `src/scoring_v03.py` | 재무 조사와 기존 GARP 점수·업종 기준 |
| `src/filing_evidence.py`, `src/official_filings.py`, `src/gemini_filing.py` | 공식 원문과 대사, 승인된 공시 기반 AI 추출 |
| `src/financial_provenance.py`, `src/research_quality.py` | 지표 출처·정의 분리, 산술과 기간 비교, 재평가와 최종 메모 게이트 |
| `tests/`, `tests_gemini/` | 스크리닝, 체크포인트, 증거 및 Gemini 회귀 테스트 |

먼저 캠페인 아티팩트의 `74_campaign_manifest.json`에서 범위와 호출 수를 확인합니다. `research/01_all_research_candidates.csv`는 탐색용 원순위, `research/32_research_stage_gate.csv`는 메모 승인 조건, `research/80_*.csv`부터 `84_*.csv`까지는 출처·대사·별도 재평가입니다. `research/71_research_dossiers/`에서 후보별 근거를 검토합니다.

AI 도구는 구현, 테스트와 원문 근거 정리를 보조했습니다. 공시의 해석, 회사 설명 검증, 투자 반증 검토와 공개 범위 승인은 사람이 맡습니다. 공급자 원본, 체크포인트, 키 및 검토자 개인정보의 재배포는 공개 전에 확인해야 합니다. [프로젝트 이력](../../CHANGELOG.md) · [제출 준비 감사](../V06_FINANCIAL_TRUST_AUDIT.md)
