# v0.6 전체 시장 연구 운영

## 비교 기준

기존 [Actions 실행 44447243252](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44447243252)의 제공 기록은 커밋 `cde78e0`에서 발견 16,671, 재무 응답 150/150, 점수 산출 137/150, 정량 검토 대상 12/150, 데이터 품질 경고 77/150을 기록했습니다. 업종 보류는 미분류 99, 공급자 휴리스틱 38, 전자·전기 부품 상세 검토 13입니다. 공식 원문과 Gemini 호출은 미실행이었고 `MEMO_READY`는 0건이었습니다. 현재 클라우드의 GitHub API 접속이 프록시 403에서 차단돼 해당 실행의 정확한 원본 입력은 가져오지 못했습니다.

현재 저수량 점검은 5개 시장에 각각 한 개의 재무 요청 대상을 배정했습니다. 종목 기준 응답은 0/5였고 10개 호출 시도를 소비했습니다. 발견된 61개 종목은 큐레이션 입력입니다. 공식 원문과 Gemini 접속 점검은 프록시가 403으로 거절했으며 `DART_API_KEY`, `EDINET_API_KEY`, `GEMINI_API_KEY`가 확인되지 않았습니다. 발행처별 접근 방식과 승인 파일은 [공식 공시 검증 가이드](V06_OFFICIAL_VALIDATION.md)에 있습니다.

## 영속 사이클

`initialize`는 기존 다섯 시장 발견 경로를 실행하고 `11`의 발견 행과 `12`의 출처 로그를 동결합니다. 원래 행은 보존하고 재무 호출은 시장별로 정렬된 고유 종목 코드에 한 번씩 배정합니다. 발견 입력이 제한된 때는 이를 `expanded_discovery_markets`에 남깁니다. `FULL_CYCLE_COMPLETE`는 적격으로 배정된 스냅샷의 처리 결과입니다. 전체 거래소 상장 모집단 완전성은 `universe_census_verified`에 별도로 기록합니다.

`batch`는 초기 실행 ID로 계획을 내려받고, 같은 저장소의 최신 롤업 및 이후에 완료된 샤드 아티팩트를 복원합니다. SHA-256, 계획·스키마·공급자 버전, 종목 집합, SQLite 무결성과 시도 이력을 확인합니다. 서로 갈라진 이력은 복원을 차단합니다. 한 연구 사이클의 실행은 기존 워크플로의 동시성 그룹에서 직렬화하고, 한 실행 안에서 다른 샤드만 병렬 처리합니다. 로컬 SQLite에서 종목 예약과 완료 갱신은 트랜잭션과 예약 토큰을 사용합니다. 중단된 요청은 15분 예약 기간이 지나야 재시도 대상이 됩니다. 사용 가능한 완료 응답은 다시 호출하지 않습니다.

- 초기 계획, 롤업, 개별 샤드 아티팩트 보존 요청은 90일입니다. GitHub의 저장소 및 조직 정책과 수동 삭제에 따라 더 짧을 수 있습니다. 보고서는 30일, 임시 워킹 세트 및 일일 예약 기록은 2일입니다. 장기 보관이 필요한 경우 정책이 허용하는 별도 보관 위치에 계획과 최신 롤업을 내려받습니다. 초기 계획이 만료되면 Actions 자동 복원은 멈추며, 보관본으로 로컬 실행하거나 따로 새 사이클을 시작할 수 있습니다.
- 키, 원문, Gemini 응답 캐시는 체크포인트 아티팩트에 포함하지 않습니다. 정규화된 공급자 수치에는 별도 공유 권한이 필요합니다. 실행 저장소의 아티팩트 가시성과 공급자 라이선스에서 허용할 때만 `GARP_ALLOW_FINANCIAL_CHECKPOINT_ARTIFACTS=1`을 설정합니다.
- 워커가 시작하기 전에 UTC 일자별 예산을 예약합니다. 중단되거나 미사용된 예약도 해당 날짜의 사용 가능량을 줄입니다. 날짜가 바뀐 워커는 호출을 중단합니다. 플랫폼의 일일 한도는 사이클 단위의 논리적 공급자 호출 수입니다. 공급자 SDK의 내부 HTTP 요청과 여러 사이클 또는 다른 프로젝트의 호출은 별도로 관리해야 합니다.
- 공급자 요청을 순차 처리하는 각 워커는 기본 2초 간격을 두고, 네트워크 오류 backoff와 최대 3회 시도를 사용합니다. 401·403·429 또는 공급자 속도 제한 예외를 만나면 해당 샤드의 호출을 중단하고, 다음 디스패치에서 저장된 24시간 공급자 보류를 적용합니다. 작업 진행과 복원은 새 수동 디스패치로 수행합니다. 서로 다른 사이클의 총 예산을 운영자가 조정하며 자동 연쇄 실행은 사용하지 않습니다.
- 데이터 수집은 여러 날짜에 걸칠 수 있습니다. 전체 사이클 보고 시점은 수집 완료된 관측에 적용하며 시작일을 역사적 데이터 시점으로 표시하지 않습니다. 종목별 취득 시각과 공급자가 제공한 최근 분기 날짜를 보존합니다. 공급자 응답이 취득일보다 미래의 회계 기간을 표시하거나 역사적 재생 파일의 명시적 시점이 기준일을 넘는 경우는 평가에서 제외합니다.

`aggregate`는 모든 완료 샤드를 한 번에 합쳐 기존 점수와 검토 절차를 재사용합니다. 미완료 및 공급자 실패 종목은 `68` 상태 파일과 시장별 분모에 남습니다. `69`는 원래 발견 목록, `70`은 같은 금융 관측치의 기존·신규 분류, 점수와 적격성 비교입니다. 공식 증거 옵션을 명시한 `aggregate`에서도 승인된 소량만 처리합니다. 검토 및 가치평가 결정을 그대로 적용하고 새 사람 확인을 생성하지 않습니다.

## Actions 입력 예시

기존 `run-research-v05.yml`에서 아래 입력을 사용합니다. 생략한 입력은 기본값을 사용합니다. 준비 및 쓰기 권한은 실행 저장소의 Actions 설정을 따릅니다.

| 실행 | 입력 |
|---|---|
| 안전한 소량 점검 | `cycle_mode=off`, `cycle_market=All`, `discovery_only=false`, `full_universe=false`, `max_symbols=5`, `financial_budget=10`, `evidence_mode=off`, `fx_mode=off`, `enable_gemini=false` |
| 초기 목록만 확인 | `cycle_mode=off`, `discovery_only=true`, `china_only=false`, `enable_gemini=false` |
| 전체 시장 동결 | `cycle_mode=initialize`, `full_universe=true`, `china_only=false`, `per_region=90`, `enable_gemini=false`. 기존 허가된 중국 목록 번들이 필요하면 `use_private_listing_bundle=true`. 발행된 실행 ID를 이후 `cycle_state`로 사용합니다. |
| 복원·계속 테스트 | `cycle_mode=batch`, `cycle_state=<초기 실행 ID>`, `full_universe=true`, `cycle_market=Korea`, `financial_budget=2`, `enable_gemini=false`. 같은 입력으로 새 디스패치를 한 번 더 실행합니다. 완료 종목의 시도 횟수가 증가하지 않는지 `68`에서 확인합니다. |
| 전체 시장 배치 | `cycle_mode=batch`, `cycle_state=<초기 실행 ID>`, `full_universe=true`, `cycle_market=All`, `financial_budget=25`, `enable_gemini=false`. 일일 예산 및 공급자 제한 안에서 새 실행을 시작합니다. |
| 최종 취합 | `cycle_mode=aggregate`, `cycle_state=<초기 실행 ID>`, `enable_gemini=false`. 재무 공급자를 호출하지 않고 상태와 보고서를 생성합니다. |
| 승인 원문/Gemini 소량 점검 | `cycle_mode=off`, `max_symbols=5`, `financial_budget=10`, `filing_budget=5`, `official_filing_requests=<승인 요청 CSV>`, `gemini_approved_sources=<승인 원문 CSV>`, `enable_gemini=true`, `gemini_approved_only=true`, `gemini_max_documents=1`, `gemini_max_requests=2`, `fx_mode=off`. 완료 사이클에는 같은 증거 입력을 `cycle_mode=aggregate`와 초기 실행 ID로 사용할 수 있습니다. |

역사적 이전 실행의 `11`과 `12`를 승인된 경로로 가지고 있다면 로컬에서 그대로 동결할 수 있습니다.

```bash
python -m src.research_cycle freeze --input /private/discovery-artifact --plan /private/plan \
  --cycle-id asia-cycle --shard-size 100
python -m src.research_cycle restore --plan /private/plan --state /private/state \
  --input /private/downloaded-checkpoints
python -m src.research_cycle aggregate --plan /private/plan --state /private/state \
  --classification /private/reviewed-classification.csv --output outputs/cycle-review
```

### 설정 변수 및 키

- 재무 작업의 저장소 변수는 `GARP_ALLOW_FINANCIAL_CHECKPOINT_ARTIFACTS=1`, 명시적 `GARP_CYCLE_DAILY_BUDGET`입니다. 소량 예시는 각각 `GARP_CYCLE_SHARD_SIZE=100`, `GARP_CYCLE_MAX_SHARDS=4`, `GARP_CYCLE_PARALLELISM=2`, `GARP_CYCLE_REQUEST_DELAY=2`입니다. 복원 테스트에서는 일일 예산 10과 최대 샤드 1을 사용합니다. 전체 시장 운영 전 공급자의 승인된 예산을 설정합니다. 체크포인트 복원은 저장소의 기본 Actions 토큰에 읽기 권한을 사용합니다.
- 분류 CSV는 선택적 저장소 변수 `GARP_CLASSIFICATION_REGISTRY`로 연결합니다. 열은 `ticker,issuer_id,security_type,share_class,counter,peer_group,source_kind,source_url,source_date,reviewed_by,review_date`입니다. 출처는 `OFFICIAL_EXCHANGE`, `OFFICIAL_ISSUER`, `CURATED`, `SOURCE_GROUNDED_GEMINI`, `VENDOR` 중 하나입니다. 법인 ID에는 등록부 또는 ISO 국가 등 네임스페이스를 포함합니다. 명시적으로 검토된 동일 법인은 후보 상세 조사에서 한 대표만 선택하고 개별 종목과 카운터는 보존합니다. 사례가 없는 기업의 분류는 계속 보류됩니다.
- 실제 증거 사용 시에만 `DART_API_KEY`, `EDINET_API_KEY`, `GEMINI_API_KEY`를 Secrets로 설정합니다. OpenDART 요청과 비교 가능한 공급자 관측치 파일은 `GARP_OPENDART_REQUESTS`, `GARP_FILING_VENDOR_EXPORT` 변수로 연결합니다. 기존 목록 공급자·비공개 번들의 인증은 기존 설정을 사용합니다.
- Gemini는 `GARP_GEMINI_MODEL`에서 모델 ID를 지정합니다. 기본값은 `gemini-3.8-flash`입니다. 자료·모델·스키마·요청 내용을 해시한 선택적 로컬 SQLite 캐시를 사용합니다. 사용량은 API 토큰 메타데이터의 실제 보고값입니다. 입력 한도는 프롬프트와 스키마의 UTF-8 바이트 예약이며 토크나이저의 실측값이 아닙니다. 출력은 요청마다 상한을 적용하고 실행당 예약량도 제한합니다. 기본 상한은 문서 3, 전체 요청 9, 입력 250,000 예약 단위, 출력 9,216 토큰이며 Actions의 기본 활성화 설정은 문서 1, 호출 2입니다.
- 일반 Gemini 점검에서 `GARP_GEMINI_TOTAL_INPUT_BUDGET`, `GARP_GEMINI_TOTAL_OUTPUT_BUDGET`을 낮출 수 있습니다. 모델의 확인된 백만 토큰당 USD 단가를 `GARP_GEMINI_INPUT_PRICE`, `GARP_GEMINI_OUTPUT_PRICE`에 넣으면 보고된 응답 토큰으로 비용을 추정합니다. 실제 청구서에 대한 검증은 별도로 필요합니다. 이번 실행의 Gemini 호출은 0건입니다.

### 원문 재생과 검증 상태

공식 원문을 내려받을 수 없다면 권한 있는 보관본을 파일명 SHA-256으로 준비합니다. `python -m src.official_filings --requests /private/approved.csv --source-dir /private/checked --replay-dir /private/originals --budget 5`로 파서만 재현할 수 있습니다. EDINET 재생은 날짜·기간 외에 승인한 문서 ID도 요구합니다. 전체 연구의 `--official-replay-dir`도 같은 형식을 사용합니다. 재생 데이터는 `OFFICIAL_REPLAY`로 구분되고 실시간 성공률에서 제외됩니다. OpenDART 보관분은 기존 승인 export와 원본 해시 경로도 사용할 수 있습니다.

원문 취득과 회계 범위 파싱, 비교 가능한 관측치, 수치 대조 상태, Gemini 증거, 분석가 확인을 각각 봅니다. 두 수치가 거래 통화나 기준 기간을 공유하지 않으면 대조에 사용하지 않습니다. 수치 대조 기본 허용 오차는 2%입니다. Gemini 응답의 출처 일치 검사를 유지하며 일치하지 않는 값과 모델 실패/할당량 응답도 기록합니다. 기존 `MEMO_READY` 게이트에는 사람 검토가 필요합니다.
