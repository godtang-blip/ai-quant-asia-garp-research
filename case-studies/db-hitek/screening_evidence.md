# DB하이텍 | 스크리닝·가치평가 근거

[사례 개요](README.md) · [보고서 PDF](db-hitek-equity-research-2026-11-20.pdf) · [기계 판독 근거와 해시](screening_evidence.json)

## 스크리닝 기록

- 생성 시각 **2026-11-19 08:40:34.760288 UTC / 17:40:34.760288 KST**. 첨부 `04_run_metadata.json`의 `pipeline_revision=0.3.1`, `data_mode=SNAPSHOT_REPLAY_NOT_LIVE`, `discovery_mode=off`를 그대로 보존했다.
- 기존 등록 61개와 이전에 발견한 16,610개를 포함해 감시 목록 **16,671개**를 재생했다. 원본 필드 `fetched_n=16671`과 `fetch_failures_n=16171`의 차이인 **500건**은 성공한 보관 재무 레코드다. `rankable_n=439`이며, 이 실행에서 500번의 신규 네트워크 호출이 있었다는 뜻으로 사용하지 않는다.
- 첨부 `02_research_shortlist.csv`는 10행으로 `shortlist_n=10`과 일치했다. `03_research_report.md`의 가시 후보 표는 15행을 표시하므로 표의 미리보기 행 수와 제출된 shortlist 크기를 구분했다.
- CSV 원본 행 순서에서 TSMC(`2330.TW`)가 1위·80.55점, DB하이텍(`000990.KS`)이 2위·77.15점이다. DB하이텍의 입력 충족률은 90%이고 `CURATED_LIST` 및 `is_new_discovery=false`가 확인된다. 원본 Markdown은 소수 한 자리로 표시한다. PDF 1쪽의 정밀 수치 및 다른 비교행도 첨부 CSV와 일치했다.
- `filing_verification=NOT_PERFORMED_ON_PRIMARY_STATEMENTS`, `memo_verified_ready_n=0`, `actual_trades=NONE`, `expected_return_backtest=NOT_PERFORMED`, `score_calibration=NOT_PERFORMED`이다. 파일에 정확한 실행 코드 SHA와 Actions run ID가 없음을 기록했다. 이 재생은 [라이브 상장 목록 실행 A](../../docs/FIVE_MARKET_DISCOVERY_MILESTONE.md) 및 [v0.6 통합 캠페인 집계](../../docs/archive/README_v06_pre_portfolio.md)와 별개다.

## 보고서와 모델 대사

| 항목 | 확인한 수치와 처리 |
|---|---|
| 회사 발표 인용 | PDF와 워크북은 2026-11-12 회사 IR의 3Q26 연결 매출 4,034억원, 영업이익 900억원 및 전년 동기 증가율 +14%/+7%를 인용한다. PDF는 증권사 증가율 +8%/+12%와의 차이를 미대사로 남겼다. 이번 정리에서 IR·DART 원문은 클라우드 접근 제한으로 재확인하지 못했다. |
| 장기 매출 | 보고서의 2030년 파운드리 목표 1.8조원은 경영진 계획이다. 1조 5,925억원은 연구자 독립 추정의 반올림 값이며 실적·회사 가이던스와 구별한다. |
| 종가와 시점 | 보고서와 v15 브리지는 **2026-11-20 종가 68,500원**을 인용한다. PDF S8과 워크북 v15의 시세 출처는 서로 다른 웹사이트를 가리킨다. 이 정리에서 거래소 종가는 별도로 확인하지 못했다. 9월 30일 금융자산·주식수와 12월 31일 DCF 평가일의 차이가 남는다. |
| 조건부 가치 | PDF 7쪽과 워크북 `v15_Decision_Bridge!L17:L19`는 원 단위 반올림 후 **59,458 / 67,254 / 73,851원**으로 일치한다. 보고서 인용 종가 대비 **−13.2% / −1.8% / +7.8%**는 산술 차이다. 확정 기대수익률이나 목표주가로 사용할 수 없다. |
| 결론 | **Watch / 신규 편입 보류**. WACC의 독립 추정과 영구 CAPEX·장기 RONIC 검증, 영업 필수 현금·자회사·비지배지분·교환사채의 경제적 조정이 남아 있다. |

보고서가 인용한 출처는 회사의 [3분기 발표](https://www.dbhitek.com/kr/media/news/view/2789), [기업가치 제고계획](https://www.dbhitek.com/files/551/2026_Corporate_Value_Up_Plan_DB_HiTek_KR.pdf), [DART 분기보고서](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261113001333), [KB 증권 WACC 참고자료](https://kbthink.com/securities-view.html?docId=20261112194633533K)다. 종가 출처는 [PDF의 시세 참조](https://www.kokstock.com/stock/item.asp?item_cd=000990) 및 [워크북의 시세 참조](https://kr.investing.com/equities/dongbu-hitek-historical-data)다.

### DCF 검산

v15 본업 FCFF의 2027~2031년 값은 각각 1,232.9432 / 2,878.5144 / 3,251.6246 / 3,361.1837 / 3,468.0247억원이다. 2032년 NOPAT 2,735.1887억원과 영구성장률 2%가 공통 가정이다. 2032년 FCFF는 `NOPAT × (1 − g/RONIC)`, 영구가치의 현재가치는 `FCFF2032 ÷ (WACC − g) ÷ (1 + WACC)^5`로 계산했다. 두 현재가치를 합한 본업 EV에 9월 말 별도 순유동 금융자산 4,574.1596억원을 전액 더하고, 자회사 가치를 계산상 0으로 둔 뒤 자기주식을 제외한 42,626,920주로 나눴다.

| 시나리오 | WACC | RONIC | 본업 EV (억원) | 부분 주당가치 (원) |
|---|---:|---:|---:|---:|
| 보수 | 12.50% | 8.6% | 20,771 | 59,458 |
| 기준 | 11.64% | 15.0% | 24,094 | 67,254 |
| 낙관 | 10.80% | 20.0% | 26,906 | 73,851 |

위 숫자는 통합문서의 저장값과 독립 산술로 대사했다. 워크북 원본에는 내부 메모가 있어 이 저장소에는 최소 검산 입력과 해시를 기록했다. 공개 가능한 발췌 범위와 전체 워크북 공유 여부는 별도 검토 대상이다.

## 파생 방법 및 보관

[JSON](screening_evidence.json)은 첨부 ZIP을 푼 뒤 메타데이터의 제한된 필드, 순서 기준 CSV 상위 두 행, DCF 검산 입력을 발췌한 파일이다. 재생 성공 수는 메타데이터 차감으로 계산했다. JSON의 해시는 바이트 변경 없이 추출한 원본 파일 기준이다. 원본 스냅샷·원본 Markdown·워크북 전체에는 공급자 행과 내부 문구가 있어 저장소 밖의 전달본에 보관했다. PDF는 첨부 원본 그대로이며 SHA-256을 함께 남겼다.
