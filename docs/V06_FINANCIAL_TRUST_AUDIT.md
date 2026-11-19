# 재무 데이터 신뢰성 및 제출 준비 감사

범위는 PR #4의 v0.6 연구 경로와 동결 사이클 `44456766424`입니다. 기존 5개 시장 수집 계획, 500건의 누적 재무 수집 시도, 기존 체크포인트와 GARP 가중치·앵커는 이번 평가의 기준입니다. 새 캠페인이나 Full-sweep을 실행하지 않았습니다.

## 유키구니 검증 결과

요청에 제공된 2026-11-19 스냅샷 발췌와 회사 전망 발췌로 산술을 재현했습니다. 이 값들은 실제 사례로 제공된 값입니다. 회귀 테스트의 승인된 출처·가격·타사 순위 자료는 별도의 합성 fixture입니다.

| 항목 | 기존 입력 | 검증 결과 |
| --- | --- | --- |
| 주가 | 1,137 JPY | 제공된 스냅샷 가격. 원문과 가격 시각 독립 검증 보류 |
| 공급자 Forward EPS | 158 JPY | 원본 보존. 적용 기간, EPS 정의와 산정 근거 미확인 |
| 공급자 Forward PER | 7.1962배 | 1,137 ÷ 158 = 7.1962배. 내부 산술 일치 |
| 회사 전망 FY2027 EPS | 63.69 JPY | 제공된 회사 전망 발췌. 원문 URL, 정확한 적용기간과 주식 기준 독립 검증 보류 |
| 회사 전망을 적용한 관측 가격 비율 | — | 1,137 ÷ 63.69 = 17.8521배. 비교용이며 점수 입력 승인 보류 |
| 별도 TTM EPS | 약 97.76 JPY | Forward와 기간이 다름. 비교 보류 |
| EPS 차이 | — | 94.31 JPY. 기간 미일치 또는 근거 부족 상태 `PERIOD_MISMATCH_OR_UNRESOLVED` |
| 점수와 순위 | 운영 아티팩트 독립 접근 불가 | 기존 값 유지. 승인된 입력과 운영 후보군이 확보되기 전까지 새 점수·순위는 공란 |
| 투자 메모 기준 | 공급자 수치가 탐색에 사용됨 | `HOLD_FORWARD_INPUT_NOT_REVIEWED` |

`python -m src.financial_provenance case`로 발췌값과 결과를 함께 확인할 수 있습니다. 발행사 IR·TDnet과 Actions의 원본 접근은 이 작업 공간에서 프록시 HTTP 403으로 차단됐습니다. 독립적인 공시 입수, 수치 확인 및 실제 500건 순위 재계산은 수행하지 못했습니다.

IFRS 총수익과 `PRODUCT_SALES`는 별도 정의입니다. `IFRS_OPERATING_INCOME`과 `ISSUER_CORE_OPERATING_INCOME`도 별도 정의입니다. Core는 `NON_IFRS_COMPANY_DEFINED` 및 `COMPANY_DEFINED_CORE`로만 기록하며 해당 발행사의 조정 기준에 묶입니다. 일반 순이익 또는 EPS로 환산하거나 다른 회사의 Core와 직접 대사하지 않습니다.

## 산출물과 사용법

| 파일 | 의미 |
| --- | --- |
| `80_vendor_metric_provenance.csv` | 공급자 원본 필드와 값, URL, 수집 일시, 정의·기간·연결 범위·회계 기준·조정·통화·단위·주식 기준. 모르는 정보는 공란이며 검증 상태를 별도 표기 |
| `81_official_metric_observations.csv` | 공식 공시 추출/전사값, 출처·위치·원본 SHA-256 및 출처 확인 상태 |
| `82_analyst_metric_reviews.csv` | 관측값의 SHA-256에 묶인 검토 기록, 날짜와 Forward 밸류에이션 승인 여부 |
| `83_financial_metric_comparison.csv` | 정의·기간·회계 기준·범위·통화·단위가 비교 가능한 경우의 차이. 동일 소스 재사용, 맥락 누락 및 단위 차이는 별도 상태 |
| `84_forward_valuation_reassessment.csv` | 내부 가격/EPS/PER 검산, 기존 점수·순위, 승인된 회사 전망 기반 PER를 반영한 별도 점수·순위와 차이 이유 |

기존 탐색용 순위는 `01_all_research_candidates.csv`에 남습니다. 새 순위는 동일 후보군에서 승인된 Forward PER만 대체한 시나리오입니다. 나머지 지표는 기존 탐색용 입력입니다. 공식 EPS 검토와 가격·통화·수집 시각·주식 기준 확인은 별개이며, 둘을 통과해야 재평가됩니다. 메모 승격에는 기존 공식 수치, 밸류에이션, 반증과 애널리스트 승인 조건도 적용됩니다. 최종 메모 목록은 종목코드 순으로 표시합니다.

합성 후보 두 개의 재평가에서는 검토된 PER가 5배에서 20배로 바뀐 후보의 점수가 70.39에서 65.33으로, 순위가 1위에서 2위로 바뀌었습니다. 다른 후보의 점수는 69.45로 유지되었고 순위는 2위에서 1위로 바뀌었습니다. 이 테스트는 입력 대체의 영향만 보여 주며 유키구니 등의 실운영 순위를 재현한 결과가 아닙니다.

기존 최종 순위 CSV가 있으면 README의 `audit-ranked`에 `--metric-evidence-dir /path/to/private-evidence`를 추가합니다. 이 경로는 집계나 공시·Gemini 호출 없이 입력 순서와 SHA-256을 보존하고 별도 `85_financial_provenance_manifest.json`을 작성합니다. 공식 원문 및 검토 입력은 아래 절차로 따로 제공합니다.

보관 중인 입력이 Plan과 SQLite 사본이라면 `python -m src.research_cycle aggregate --plan /path/to/plan --state /path/to/state --output outputs/replay --metric-evidence-dir /path/to/private-evidence`로 오프라인 보고서를 만들 수 있습니다. 기존 Research-now 순위와 일대일 비교할 때는 원래 순위 CSV를 사용합니다. 통합 실행의 기본 검토 입력 경로는 유니버스 CSV 옆 `financial_evidence/`입니다. 파일이 없으면 기존 캠페인은 정상 진행하며 새 승인은 생성되지 않습니다.

1. 선택적으로 `vendor_context.csv`에 `ticker,snapshot_field,collected_at` 키로 증빙된 정의와 기간을 추가합니다. 값과 원본 스냅샷은 직접 편집하지 않습니다.
2. `official_observations.csv`의 스키마는 `src/financial_provenance.py`의 `OBSERVATION_COLUMNS`입니다. 서류 본문에서 읽은 값, 위치, 기간, 발행일과 실수집일을 기재하고 원본을 `originals/<source_sha256>`로 둡니다. 허용되는 출처는 기존 공식 시장 경로 또는 `issuer_source_registry.csv`에 해당 종목의 확인된 URL로 정확히 등록된 발행사 경로입니다. 원본 해시 일치는 문서 무결성 확인이며 전사 내용은 사람이 확인합니다.
3. 첫 감사 결과의 `81_...`에서 정확한 `observation_sha256`을 확인합니다. `analyst_reviews.csv`에 이를 키로 `decision=CONFIRMED`, `reviewer`, `reviewed_at`를 기록합니다. Forward PER 재평가에는 스냅샷과 일치하는 `quote_value`, `quote_currency`, `quote_collected_at`, `quote_source_url`, `quote_share_basis`도 필요합니다. 관측 당시 유효한 연결 기준의 비조정 기본 또는 희석 EPS에만 적용됩니다.
4. 새 출력 경로로 재실행해 `82_...`의 승인·보류 사유와 `84_...`의 비교를 봅니다. 실제 회사 자료에는 재배포 승인된 출처만 사용하고 검토자 별칭과 원본을 별도로 보관합니다.

## 검증 범위와 제출 상태

- 기존 Research-now 재개 테스트는 복원 체크포인트를 이용한 두 파동과 Dossier 생성을 fixture로 확인합니다. 기존 EDINET/Gemini 통합 테스트는 공식 경로와 통신하는 형태를 모의하며 HTTP 504 복구도 포함합니다.
- 로컬 전체 회귀 테스트 `python -m pytest -q tests tests_gemini`는 309개 통과했습니다.
- 실제 캠페인 집계는 제공된 운영 결과입니다. 유키구니 FY2027 원문과 공급자 추정기간, 유키구니 실운영 점수의 새 순위, 이번 커밋의 라이브 Actions·Gemini 결과는 미확인입니다.
- GitHub Actions 권한은 기본 `contents: read`, `actions: read`를 사용하며, 자동 재개 잡만 `actions: write`를 요청합니다. 공시·Gemini 키는 Secrets 참조로 전달됩니다. 새 유료 서비스나 자격증명은 추가하지 않았습니다. 공개 범위와 서버 설정은 GitHub API 403 때문에 확인하지 못했습니다.
- 추적 대상 파일, 제출 변경 및 Git 이력을 주요 토큰·개인 키·URL 내 인증정보 패턴으로 검사했으며 일치하는 문자열은 발견되지 않았습니다.
- `.gitignore`는 로컬 검토 입력, SQLite 및 환경 파일을 제외합니다. 공개 전에는 저장소 접근범위, Secrets 권한, 아티팩트 다운로드 권한, Yahoo 및 타사 공급자 원본·파생물의 재배포 조건, 검토자 정보와 공시 원문의 공개 범위를 소유자가 확인해야 합니다. 기존 아티팩트나 체크포인트의 삭제·변경은 이번 감사 범위에 포함되지 않습니다.
- 사용자 검토용 PR 준비 단계입니다. 병합, 저장소 공개, 운영 실행은 이번 작업에서 수행하지 않았습니다.
