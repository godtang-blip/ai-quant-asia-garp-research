# v0.6 공식 공시 자동 취득과 검증

## 발행처와 접근 방식

| 범위 | 공식 운영 경로 | 처리 |
|---|---|---|
| 일본 JPX | [금융청 EDINET API 안내](https://disclosure2.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html) | API v2에서 공개일별 `documents.json?date=YYYY-MM-DD&type=2`를 조회합니다. EDINET 코드·종목 코드·보고 기간이 일치하는 공개 유가증권보고서(120)를 찾고 `documents/{docID}?type=1`로 XBRL ZIP을 받습니다. 두 요청에 `EDINET_API_KEY`를 구독 키로 사용합니다. |
| 중국 SSE Main/STAR | [SSE 상장사 공시](https://www.sse.com.cn/disclosure/listedinfo/announcement/) | 승인한 원문 링크에서 PDF/HTML을 받습니다. 허용 호스트는 `www.sse.com.cn`, `static.sse.com.cn`입니다. |
| 중국 SZSE Main/ChiNext | [SZSE 상장사 공시](https://www.szse.cn/disclosure/listed/notice/) | 승인한 원문 링크에서 PDF/HTML을 받습니다. SZSE 공시 검색이 제공한 `www.szse.cn`, `disc.static.szse.cn`, `static.cninfo.com.cn` 링크를 사용합니다. |
| 중국 BSE | [BSE 공시](https://www.bse.cn/disclosure/announcement.html) | 승인한 `www.bse.cn` 또는 `static.bse.cn` 원문 링크에서 PDF/HTML을 받습니다. |
| 홍콩 HKEX | [HKEXnews Title Search](https://www1.hkexnews.hk/search/titlesearch.xhtml) | 검색 결과의 `www1.hkexnews.hk` 또는 `www.hkexnews.hk` 원문 링크에서 PDF/HTML을 받습니다. |
| 대만 TWSE/TPEx | [MOPS](https://mops.twse.com.tw/) 및 [공시 문서 열람](https://doc.twse.com.tw/) | MOPS에서 선택한 재무보고서의 `mops.twse.com.tw` 또는 `doc.twse.com.tw` 원문 링크에서 PDF/HTML을 받습니다. |

EDINET은 날짜와 발행사 코드로 문서를 조회합니다. 중국·홍콩·대만은 운영자가 공식 검색 화면에서 연간 연결 보고서를 선택하고 최종 HTTPS 원문 링크를 검토합니다. 파이프라인이 원문 다운로드와 재무표 추출을 수행합니다. 공시 포털 전수 검색, 로그인 또는 CAPTCHA 처리, 임의 URL 전환, OCR은 지원 범위 밖입니다. 접근이 거부되면 그대로 기록합니다.

EDINET은 공개 XBRL의 표준 taxonomy 태그, 발행사 ID, 대상 기간, 연결 공시 표시 및 ISO 통화 단위를 확인합니다. 원문 PDF/HTML은 법인명, 연결 재무표 제목, 회계연도, 현재·비교 열과 통화·단위가 식별될 때만 추출합니다. PDF는 텍스트가 있는 명확한 표, HTML은 정렬된 표를 처리합니다. 현재 지원하는 항목은 양식에 따라 매출, 영업손익, 지배기업 귀속 이익, 자산·부채·자본·현금, 영업현금흐름 등입니다. 빈 항목, 중복 값, 모호한 열·기간·회계 범위는 추출 결과를 줄일 수 있습니다. 원문 수치 대조에는 별도의 동일 정의 공급자 관측치가 필요합니다.

## 입력 파일

공식 공시 요청 CSV 헤더:

```csv
venue,ticker,issuer_id,issuer_name,period_start,period_end,publication_date,source_url,document_id,expected_sha256
```

- `venue`에는 `JPX`, `SSE_MAIN`, `SSE_STAR`, `SZSE_MAIN`, `SZSE_CHINEXT`, `BSE`, `HKEX`, `TWSE`, `TPEX`를 사용합니다. 날짜는 ISO `YYYY-MM-DD`입니다.
- EDINET의 `issuer_id`는 EDINET 코드이고 `source_url`은 비워둡니다. `document_id`를 생략하면 공개일·발행사·기간과 일치하는 고유 공시가 있어야 합니다.
- 나머지 시장의 `source_url`은 공개 검색에서 확인한 최종 원문 링크입니다. `issuer_id`는 동일 발행사의 비교 관측치에 사용하는 식별자입니다. `expected_sha256`을 지정하면 원문 바이트를 대조합니다.
- 공급자 수치 대조용 별도 CSV의 스키마는 [운영 가이드](V06_RESEARCH.md#공시-입력)를 참조합니다. 공급자 관측치는 공식 공시 원문과 별도로 준비합니다.
- Gemini 승인 CSV는 `ticker,source_url,document_date,issuer_name,date_source_url,document_title` 및 선택적 `expected_sha256,issuer_identifier`를 사용합니다. 출처·사용권을 검토한 문서만 고릅니다. 공개 PDF/HTML에만 적용되며 EDINET API용 XBRL ZIP은 결정적 파서 경로로 처리합니다.

## 재현

먼저 키 없이 출처 접속만 점검하거나 요청 CSV의 취득 경로만 실행합니다.

```bash
curl -sS --max-time 8 -o /dev/null -w '%{http_code}\n' https://www1.hkexnews.hk/search/titlesearch.xhtml
python -m src.official_filings --requests /path/to/official.csv \
  --source-dir /tmp/garp-filing-originals --budget 5
```

스크리닝·수치 대조·Gemini까지 연결하려면 확인한 입력 경로와 필요한 키를 설정하고 실행합니다.

```bash
python -m src.v06 --discover-mode all5_official --max-symbols 5 \
  --financial-budget 5 --filing-budget 5 \
  --official-filing-requests /path/to/official.csv \
  --vendor-export /path/to/comparable-vendor.csv \
  --source-dir /tmp/garp-filing-originals \
  --approved-sources /path/to/approved.csv --enable-gemini --gemini-approved-only \
  --max-documents 1 --max-requests 2 --output outputs/official-canary
```

`--gemini-preflight`는 키 없이 문서 파싱까지만 시도합니다. `--gemini-approved-only`는 순위·증거 원장을 기다리지 않고 명시적으로 승인한 날짜 있는 문서로 소규모 점검을 수행합니다. 후보 선정 기준과 가치평가 단계는 그대로 유지됩니다. `--gemini-replay-dir`는 명시적으로 승인된 SHA-256과 일치하는 `.source` 스냅샷을 사용하는 별도 옵션입니다.

### GitHub Actions

1. `.github/workflows/run-research-v05.yml`는 기본 브랜치에 등록된 후 수동 실행 화면에서 브랜치를 선택할 수 있습니다. 후보 브랜치에만 새로 있는 입력은 기본 브랜치 반영 후 수동 실행 화면에 나타날 수 있습니다.
2. 필요한 저장소 Secrets를 설정합니다. EDINET은 `EDINET_API_KEY`, OpenDART는 기존 `DART_API_KEY`, Gemini는 `GEMINI_API_KEY`를 사용합니다. 모델 ID를 변경하려면 저장소 변수 `GARP_GEMINI_MODEL`을 지정합니다. 미설정 시 구현 기본값은 `gemini-3.8-flash`입니다.
3. 공유가 승인된 입력 CSV를 실행 브랜치에 둡니다. 공식 파일은 `official_filing_requests`, Gemini 승인 파일은 `gemini_approved_sources`에 체크아웃 기준 경로를 입력합니다. 별도 수치 대조와 한국 API 요청 파일은 저장소 변수 `GARP_FILING_VENDOR_EXPORT`, `GARP_OPENDART_REQUESTS`에 설정합니다. 경로는 체크아웃 내 CSV만 받습니다. 원문은 러너 임시 디렉터리에 저장합니다.
4. 소규모 통합 점검에는 `filing_budget: 5`, `financial_budget: 5`, `max_symbols: 5`, `enable_gemini: true`, `gemini_approved_only: true`, `gemini_max_documents: 1`, `gemini_max_requests: 2`를 사용합니다. 일반 연구에서 승인 문서를 스크리닝 후보로 제한하려면 `gemini_approved_only: false`를 유지합니다. `discovery_only: true`로 전체 목록 경로를 독립 재현할 수 있습니다.
5. 실행 로그와 `67_v06_run_manifest.json`의 `outcomes`, `filing_attempts`를 확인합니다. Gemini는 `63_gemini_evidence.json`에서 API 응답 수와 문서별 추출 상태를 각각 확인합니다. API 응답은 출처 대조를 통과한 수치와 별개입니다.

### 성공률 정의

- 재무 응답은 실제 네트워크 호출 대상으로 선택된 고유 종목 가운데 공급자 응답을 받은 종목 수입니다. 재시도·체크포인트 적중·오프라인 스냅샷은 이 분모에 중복 포함되지 않습니다. 별도로 점수를 계산한 종목을 집계합니다.
- 공식 응답·문서 취득은 각각 실제 스케줄 실행 수 대비 응답 본문 수와 승인 원문 검사 완료 문서 수입니다. 명세서 파싱은 취득 문서 중 지원 관측치가 있는 문서 수입니다. 수치 대조는 파싱된 원문 중 독립 공급자 수치와 최소 한 관측치가 대조된 문서 수입니다. 문서의 다른 항목에 오류가 있는지는 대조 CSV를 확인합니다.
- 보고서 생성은 비어 있지 않은 결과 파일 수를 예정된 두 파일과 비교합니다. 보류 사유가 기록된 빈 후보 목록도 정상 보고서입니다. 분모가 0인 비율은 `null`입니다.
