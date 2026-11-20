# 코드 구조와 재현 방법

[프로젝트 개요](../README.md) · [DB하이텍 사례](../case-studies/db-hitek/README.md) · [개발·실패 기록](AI_DEVELOPMENT_TRAIL.md)

## 파이프라인 코드

| 단계 | 코드와 검토 범위 |
|---|---|
| 상장종목 수집 | [`discovery_v031.py`](../src/discovery_v031.py), [`discovery_smoke.py`](../src/discovery_smoke.py). 거래소와 허가된 공급자 경로, 출처·누락 로그. |
| 재무 스크리닝 | [`v031.py`](../src/v031.py), [`scoring_v03.py`](../src/scoring_v03.py). 업종별 앵커, 입력 충족률, 품질 게이트 및 연구 우선순위. |
| 증거 검토 | [`official_filings.py`](../src/official_filings.py), [`gemini_filing.py`](../src/gemini_filing.py), [`financial_provenance.py`](../src/financial_provenance.py). 원문 취득, 승인된 문서 기반 추출, 기간·정의 대사와 미검증 입력 경고. |
| 캠페인 재개 | [`research_cycle.py`](../src/research_cycle.py), [`research_campaign.py`](../src/research_campaign.py). 동결 모집단, 체크포인트, 호출 예산. |
| 사람의 판단 | 연구자가 공시와 손익 범위, CAPEX·DCF 가정 및 반대 근거를 검토한다. [DB하이텍 보고서](../case-studies/db-hitek/db-hitek-equity-research-2026-11-20.pdf)는 별도 분석 산출물이다. |

## 로컬 실행

저장소 루트에서 Python 3.11을 권장한다. 테스트는 샘플과 회귀 조건을 확인한다. 저장소의 실제 데이터 경로에 대한 접근 및 백테스트와는 별개다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-gemini.txt
python -m pytest -q tests
python -m pytest -q tests_gemini
python -m src.discovery_smoke --output discovery-smoke
```

`discovery-smoke`는 새 출력 경로여야 한다. 스모크는 외부 목록만 시도한다. 프로세스가 성공하더라도 `12_discovery_sources_log.csv`와 `47_venue_coverage.csv`에서 출처별 상태와 `live_supported_n`을 확인한다. 이번 포트폴리오 정리의 로컬 스모크는 curated 61개를 유지했고, 실제 외부 상장종목 수집은 0개였다. 거래소 경로 접근과 선택 인증 설정이 필요했다.

## GitHub Actions

[수동 워크플로 YAML](../.github/workflows/run-research-v05.yml) · [캠페인 운영](V06_CAMPAIGN.md) · [공시와 Gemini 제한](V06_RESEARCH_DOSSIER.md)

- 상장 목록 점검은 `discovery_only=true`를 사용한다. 결과는 `11_discovery_universe.csv`, `12_discovery_sources_log.csv`, `47_venue_coverage.csv`에서 확인한다.
- 현재 기본 브랜치의 실행 이력은 v0.5.1, 포트폴리오의 기반인 [PR #4](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/4)의 같은 YAML은 v0.6 통합 개발 경로다. 보관 스크리닝 근거의 `pipeline_revision=0.3.1`은 별도 스냅샷 재생의 메타데이터다.
- 기존 캠페인에서 `74_campaign_manifest.json`으로 단계별 호출 수와 성공 범위를 확인한다. 출처 원문 열람·숫자 대사·Gemini 응답·사람의 메모 승인은 각각 별도다. [재무 지표 신뢰성 감사](V06_FINANCIAL_TRUST_AUDIT.md)

## 외부 공유 전 확인

1. 저장소 접근권한과 기존 Git 커밋 작성자 정보 노출 범위를 검토한다. 접근권한은 승인받은 평가자에게 필요한 범위로 설정한다.
2. 키·토큰·환경 파일을 Git 이력과 아티팩트까지 별도로 점검한다. Actions Secrets에는 값만 등록하며, 로그와 샘플에는 변수 이름만 사용한다.
3. 공급자·거래소·공시·증권사 자료의 이용 및 재배포 조건과 저장소 라이선스를 확인한다. 원본 스냅샷·체크포인트와 내부 통합문서는 공유 대상에서 제외했다.

[공시 데이터 출처와 접근 상태](V06_OFFICIAL_VALIDATION.md) · [이전 버전 실행 안내](README_v031_quickstart_legacy.md)
