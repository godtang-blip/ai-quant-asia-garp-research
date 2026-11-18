# AI Quant — Asia GARP Research (독립적인 취업 포트폴리오 연구용)

**회사와 무관한 개인 연구 프로젝트입니다. Redpoint Partners의 실제 비공개 투자 알고리즘을 구현한 것이 아닙니다.**

목표: 공개 기사에서 관찰되는 아시아 산업·밸류체인, GARP(성장성과 합리적 밸류에이션), 시장의 오해, 재평가 촉매라는 관점을 *개인 연구용 스크리닝 절차*로 구현하는 것. **후보 발굴까지만 자동화**하고, 투자 논거·반대 논거 및 투자 여부는 반드시 사람이 판단합니다.

## 구분 및 보안

- **기존 `ai-quant-v512-paper`와 `ai-quant-paper`, 통합 성과 비교 저장소를 수정하지 않습니다.**
- 이 저장소에는 모의계좌 상태, 투자 주문, 브로커 연결, 실거래 기능이 전혀 없습니다.
- 종목은 샘플 `data/universe.csv`의 28개 **수동 지정 유니버스**입니다. 아시아 전체 또는 실제 회사의 300여 개 종목을 스캔한다고 주장하지 마세요.
- Yahoo/yfinance의 기본 재무값은 검증되지 않은 스냅샷입니다. **공시 시점 기준(PIT) 데이터가 아니므로 가치투자 백테스트나 실제 투자의 증거로 사용하면 안 됩니다.**
- 순위 점수는 임의로 고안한 초안입니다. 산업·국가별 회계 기준, 통화, 특수 업종, 사업구조, 밸류에이션 레짐 차이를 충분히 보정하지 않습니다.
- 다운로드된 금융 수치와 날짜는 발행사 공시/IR로 반드시 재확인하세요. 정보 공급자의 데이터가 누락되면 `REVIEW_DATA_OR_PEERS`가 됩니다. 데이터 부족을 통과로 처리하지 않습니다.
- 실제 투자 아이디어에는 **산업 배경, 2개 이상의 비교관점, 촉매 원문, 반대 논거, 투자 판단이 틀렸다고 인정할 조건**이 필요합니다.

## 가장 빠른 실행 — GitHub Actions

1. GitHub에 새 **Private** 저장소 `ai-quant-asia-garp-research` 생성 (기존 v5.12에 업로드하지 않기).
2. 이 ZIP을 압축 해제하고 **안쪽 프로젝트 폴더의 모든 파일·숨김 `.github` 폴더**를 새 저장소 루트에 복사해 Push.
3. GitHub → **Actions** → **Asia GARP Research — Manual Only** → **Run workflow**.
4. `max_symbols`에 처음에는 `12` 입력. 처음 12개는 반도체 제조/장비/부품 비교 표본. 모두 처리하려면 `0` 입력.
5. 실행 성공 후 실행 결과의 **Artifacts**에서 `asia-garp-research-...` 내려받기.
6. `03_research_report.md`를 열고 `01_all_research_candidates.csv`의 데이터 공백/경고를 확인. 

**주의:** GitHub 서버에서 Yahoo 금융데이터가 제한(429)될 수 있습니다. 이 경우 결과를 조작해 성공으로 처리하지 말고 Colab에서 시도하세요. Python 테스트는 네트워크 없이 동작하지만 실제 데이터 수집은 런타임 연결이 필요합니다.

## Google Colab 실행

`notebooks/Run_Asia_GARP_Colab.ipynb`를 Colab에 업로드하여 열고 순서대로 실행하세요. 업로드 창에서 이 ZIP을 선택하면 실행할 수 있습니다. GitHub Actions로 정상 작동하면 Colab은 필수가 아닙니다.

## 로컬 실행

```bash
pip install -r requirements.txt
python -m pytest -q tests
python -m src.screen --max-symbols 12
```

`outputs/`에 `01_all_research_candidates.csv`, `02_research_shortlist.csv`, `03_research_report.md`, `04_run_metadata.json`를 생성합니다. 결과가 없다면 실패를 숨기지 않습니다.

## 초기 점수 산식(연구자가 만든 예시)

동종 비교군별 percentile: 매출 성장률 20%, 이익 성장률 15%, 영업이익률 15%, ROE 10%, FCF yield 15%, Forward PE 15%, P/S 10%. **이는 회사의 실제 방법론이 아니며, 정답이라고 주장하지 않습니다.** 7개 가운데 최소 5개 지표와 충분한 동종 표본이 있어야 탐색 점수를 부여합니다. 점수는 매수가격, 적정주가, 미래 기대수익률이 아닙니다.

성장주 스크리닝에서 특히 중요한 재평가 촉매와 투자 논거는 정량 데이터만으로 확인할 수 없으므로 `data/catalyst_evidence_template.csv`에 검증된 공시와 함께 수기로 작성합니다.

## 다음 확장 단계(구현되지 않음)

- 공시/실적발표 원문 PDF·HTML 수집과 원문 인용 링크·발표일 추적
- 기업별 매출 성장 동인/산업 밸류체인·국가별 비교표
- 기업 가치평가 2~3 시나리오, PSR/EV-EBITDA/DCF 등 적합성 비교 및 민감도
- LLM 간 주장 교차검증 + 사람이 투자 논거/반대 논거 승인하는 리서치 워크플로우
- 결산 기간별 시점 정합성, 다통화 변환·재무제표 공시 시차 검증

## 읽어볼 공개 자료

- [더벨 대표 프로파일 (2026-07)](https://m.thebell.co.kr/m/newsview.asp?newskey=202607091444018880101545)
- [더벨 운용 및 GARP 관련 기사 (2026-07)](https://m.thebell.co.kr/m/newsview.asp?newskey=202607091410242320104758)
- [금융투자협회 AI-Native Equity Research Intern 공고](https://www.kofia.or.kr/brd/m_96/view.do?seq=43155)

**투자 조언이 아니며 실제 계좌와 연결하면 안 됩니다.**
