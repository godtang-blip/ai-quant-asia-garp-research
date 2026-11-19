# Asia GARP v0.6 운영 가이드

Python 3.11 환경에서 실행합니다.

```bash
python -m pip install -r requirements.txt -r requirements-gemini.txt
python -m pytest -q tests tests_gemini
python -m src.v06 --discover-mode all5_official --max-symbols 25 \
  --financial-budget 25 --checkpoint /tmp/garp-financial.sqlite --output outputs/v06
```

`--full-universe`를 지정하면 발견된 전체 유니버스를 선택합니다. `--financial-budget`은 재시도를 포함한 종목 호출 예산입니다. 새 출력 디렉터리와 같은 체크포인트 및 UTC 기준일로 재실행하면 이전에 성공한 호출을 재사용합니다. 공급자 재시도는 순차 실행하며 실패 행은 다음 실행에서 다시 시도합니다. 체크포인트에 공급자 데이터가 들어 있으므로 로컬에 보관합니다. 내부 공급자 HTTP 요청 수는 종목 호출 수와 다를 수 있습니다. GitHub Actions는 실행 간 체크포인트를 보존하지 않습니다.

이전 날짜의 분석에는 `--discover-mode off --snapshot-csv SNAPSHOT --asof-date YYYY-MM-DD`를 사용합니다. 기준일 검증은 공시 및 리뷰에 적용되며 스냅샷의 시점 적합성은 운영자가 확인합니다. 기존 검토 CSV와 Bear/Base/Bull 로직을 읽기 전용으로 사용합니다. `--previous-artifacts`에는 이전 실행 디렉터리를 지정해 데이터 부족으로 제외됐던 후보의 재검토 여부를 기록할 수 있습니다. 기존 analyst 결정을 수정하지 않습니다.

## 공시 입력

`--primary-export PRIMARY.csv --vendor-export VENDOR.csv --source-dir PRIVATE_DIR`를 지정합니다. 공식 출처의 원본을 SHA-256 파일명으로 보관하고, 권한 있는 파서에서 추출한 관측치를 CSV로 제공합니다. 공시 원본은 업로드하지 않습니다. 원본 해시 검사는 바이트 무결성을 확인합니다. CSV에서 지정한 값과 위치가 원본에 존재하는지는 별도로 검토해야 합니다.

공통 열은 `ticker,issuer_id,metric,definition,period_start,period_end,period_kind,scope,statement,currency,unit,value,scale,publication_date`입니다. 공시에는 `issuer_name,venue,market,source_url,source_locator,source_sha256,provider_version,parser_version`도 필요합니다. `definition`은 공급자와 공시가 공유하는 정규화된 정의입니다. 단위는 `CURRENCY`, 주식 수는 `SHARES`, 희석 EPS는 `CURRENCY_PER_SHARE`입니다. 기간은 `FY`, `QUARTER`, `YTD`, `INSTANT`를 구분하고 연결 범위는 `CONSOLIDATED`와 `SEPARATE`로 구분합니다. 비교는 같은 기간·정의·통화·단위·범위에서만 수행합니다. `--tolerance` 기본값은 0.02입니다. 중복 관측치는 재작성 여부 검토를 위해 보류됩니다.

| 시장 | 등록 공시 출처 | 입력 경로 |
|---|---|---|
| 한국 | OpenDART 및 DART | OpenDART 키로 취득한 재무제표 또는 공식 공시의 권한 있는 정규화 export |
| 일본 | EDINET | EDINET API v2 키로 취득한 공시 또는 공식 XBRL의 권한 있는 정규화 export |
| 중국 | SSE Main/STAR, SZSE Main/ChiNext, BSE | 거래소 공시의 권한 있는 정규화 export |
| 홍콩 | HKEXnews | 승인된 공시 HTML/PDF의 권한 있는 정규화 export |
| 대만 | MOPS, TWSE/TPEx 발행사 | 공식 재무표의 권한 있는 정규화 export |

검증된 자동 인증 또는 신규 거래소별 원본 파서는 제공하지 않습니다. 출처 페이지는 [OpenDART](https://opendart.fss.or.kr/guide/main.do), [EDINET](https://disclosure2.edinet-fsa.go.jp/), [SSE](https://www.sse.com.cn/), [SZSE](https://www.szse.cn/), [BSE](https://www.bse.cn/), [HKEXnews](https://www.hkexnews.hk/), [MOPS](https://mops.twse.com.tw/)에서 확인합니다.

## 선택 Gemini 경로

기존 증거 원장에 있는 문서와 정확한 URL을 승인 목록에 기록합니다. 형식과 사전 점검 절차는 [v0.5.2 가이드](GEMINI_FILING_RESEARCH_V052.md)를 따릅니다. 통합 실행 시 `--evidence-mode full --approved-sources APPROVED.csv --enable-gemini`와 런타임의 `GEMINI_API_KEY`가 필요합니다. `--model` 또는 `GARP_GEMINI_MODEL`에서 모델을 지정합니다. 기본값 `gemini-3.8-flash`의 실제 서비스 가용성은 검증해야 합니다. 문서 수, 요청 수, 요청별 바이트 및 출력 토큰 수를 제한하고 성공 응답의 토큰 수를 기록합니다. 비용은 가격 확인 전에는 미산정입니다. 문서 분석 결과는 출처 일치 검토를 거치며 사람의 승인 단계는 기존 검토 절차를 따릅니다.

## 산출물

| 파일 | 의미 |
|---|---|
| `60_financial_coverage.csv` | 시장별 발견·요청·실제 재무 행·점수·통과·공시 관측치 집계 |
| `61_primary_source_registry.csv` | 시장·거래소·공시 발행자 및 export 공급 여부 |
| `62_numerical_reconciliation.csv` | 원본 입력·정규화값·차이·검증 상태·차단 사유 |
| `63_gemini_evidence.json` | 모델·사용량·출처 위치·관측치 또는 미실행 사유 |
| `64_exclusion_audit.csv` | 기존 스크린의 제외 사유와 선택적 전후 비교 |
| `65_five_market_shortlist.csv` | 기존 MEMO_READY 요건을 통과한 비교 후보 최대 5개 |
| `66_candidate_briefs.md` | 최대 3개 검토 요약 또는 검토 보류 사유 |
| `67_v06_run_manifest.json` | 커밋·시각·커버리지·공급자 버전·검증 상태·실패 집계 |

기존 파일명을 유지합니다. 전체 발견 종목 재무 데이터가 미확보된 경우 실행 매니페스트가 부분 결과로 표시합니다. `MACHINE_RECONCILED`는 전달된 비교 가능 수치가 허용 오차 이내라는 뜻입니다. 사람의 승인 및 투자 모델 검증은 각각 별도 상태입니다.

Actions에서 기존 연구 워크플로를 수동 실행합니다. 기본은 종목 및 호출 수 제한을 적용한 v0.6이며 `discovery_only`와 `legacy_research` 선택을 지원합니다. 공식 목록만 재확인하려면 `python -m src.discovery_smoke --output outputs/discovery`를 실행합니다.
