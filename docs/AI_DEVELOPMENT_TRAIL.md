# Human-directed, AI-assisted 개발 이력

## 기여와 책임

| 참여 | 실제 역할 |
|---|---|
| 연구자·저장소 소유자 | 5개 시장 연구 목표, 스코어링 기준, 공시 대사 요구, 후보 선정과 DB하이텍 최종 판단을 주도했다. |
| ChatGPT | 초기 Python·Colab 구현과 실험, 공시 조사, DCF 계산·검산과 보고서 초안에 실질적으로 참여했다. |
| Codex | 소유자가 정의한 과제를 PR로 구현했다. 거래소 어댑터, 오류 분석, 회귀 테스트, 수치 출처 및 문서 정리가 포함된다. |
| GitHub Actions | 워크플로를 실행하고 실행별 로그·아티팩트를 남겼다. DB하이텍 PDF와 DCF는 별도로 작성한 연구 산출물이다. |

## 코드와 PR에서 확인할 수 있는 변경

| 이력 | 확인한 내용 |
|---|---|
| 초기 ChatGPT·Colab | 작은 후보군에서 반도체 집중 및 공급자 지표 이상을 발견했다. 동종 업종 비교, 통화·기간 확인, 이상치 검토로 이어졌다. [Colab](../notebooks/Run_Asia_GARP_Colab.ipynb) · [버전별 시행착오](DEVELOPMENT_HISTORY.md) |
| 2026-11-18 KST · PR #1 | 5개 시장의 목록 범위와 시장별 조회 할당을 보완했다. `main`의 병합 기록은 `451485d`다. [PR #1](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/1) |
| PR #2 · Gemini 실험 | v0.5.2 기능 브랜치의 `f786add`에서 원문 셀 근거와 관련 테스트를 보강했다. 당시 기본 브랜치 실행 이력과 분리된다. [PR #2](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/2) |
| 2026-11-19 KST · PR #3 | SSE 페이지 요청, 중국 보드 구분, SZSE/BSE 원천별 오류·대체 경로 검증을 보완했다. `main`의 병합 기록은 `89cdeca`다. 후속 라이브 실행은 상장 코드 16,629개를 수집했다. [PR #3](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/3) · [실행 근거](FIVE_MARKET_DISCOVERY_MILESTONE.md) |
| PR #4 · v0.6 통합 | 고정 체크포인트, 제한된 공식 원문·Gemini 검증, 재무 정의 대사 및 사람의 승인 게이트를 구현했다. `11f60a4`는 기간·EPS 정의 검증, `8b4d607`은 정확히 65%인 가중 입력 충족률 경계 회귀를 다뤘다. [PR #4](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/4) · [재무 신뢰성 감사](V06_FINANCIAL_TRUST_AUDIT.md) |

## 실패와 그에 따른 수정

| 관측 | 남긴 판단·수정 |
|---|---|
| 초기 국가·업종 집중, TPEx 스키마 불일치, SSE 페이지 불일치, SZSE/BSE 공식 경로 제한 | 출처별 실패와 범위를 분리했다. QuantSonar 결과는 독립 공급자 목록으로 기록한다. [시장별 진단](CHINA_A_SHARE_DISCOVERY.md) |
| Actions `#44451976790`에서 빈 뉴스 CSV로 `EmptyDataError` | `89fe8ec`에서 빈 데이터와 손상된 형식을 구분하도록 수정했다. [실행 기록](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44451976790) |
| Actions `#44452826314`의 동시 체크포인트 테스트에서 시도 이력 불일치 | `16d645b`에서 SQLite의 동일 스냅샷으로 무결성을 검증하도록 수정했다. [실행 기록](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44452826314) |
| Aggregate `#44468923747`에서 EDINET 연결 범위 파싱 실패와 Gemini HTTP 504 | `68be877`에서 공시 엔터티·컨텍스트 처리와 제한된 재시도를 보강했다. 이후 Gemini HTTP 400 대응은 `83f95c6`의 요청 설정·오류 진단에 남겼다. [실행 기록](https://github.com/godtang-blip/ai-quant-asia-garp-research/actions/runs/44468923747) |
| 정의 미확인 공급자 Forward PER, 65% 경계에서 발생한 누락 | 원본 순위를 유지하고 민감도 분석을 별도로 실행했다. 정확히 65%인 경우의 점수 산정과 70%의 1차 게이트를 구분했다. 이 결과로 본 사례의 보관 스크리닝 순위를 덮어쓰지 않았다. [경계 수정 커밋](https://github.com/godtang-blip/ai-quant-asia-garp-research/commit/8b4d6072adee25395930c53076121b57b5810603) |

테스트는 구현 동작을, 실행 로그는 접근·실패를, 공시와 DCF는 분석 근거를 보여준다. 어느 한 단계의 성공으로 전체 상장 시장의 재무 검증이나 수익률이 입증되지는 않는다. [CHANGELOG](../CHANGELOG.md) · [포트폴리오 사례와 증거](../case-studies/db-hitek/screening_evidence.md)
