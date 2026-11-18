# Asia GARP Research v0.2.1 업데이트 안내

1. 기존 **ai-quant-asia-garp-research** 저장소만 업데이트합니다. v4.2/v5.12/성과비교 프로젝트는 건드리지 않습니다.
2. ZIP 압축을 풀고 `ai-quant-asia-garp-research/` 폴더 **안쪽 내용 전체를** 기존 프로젝트 루트에 덮어써 Push 합니다. `.github`도 포함합니다.
3. Actions → **Asia GARP Research v0.2.1 — Manual Only** → Run workflow. `max_symbols=12`로 성공 확인 후 필요하면 `0`(61개 전체).
4. 완료된 Actions 실행 하단 **Artifacts → asia-garp-research-v021-...** ZIP 다운로드.
5. `03_research_report.md`와 `09_filing_verification_queue.csv`를 먼저 읽고, 실제 공시 확인이 없는 후보는 투자 추천이라고 표현하지 않습니다.
6. 공개 포트폴리오는 `PORTFOLIO_README_GUIDE.md`를 참조합니다. 채용용은 기업 투자메모가 중심이며 자동화의 설명은 짧게 첨부합니다.

**중요:** 이번 버전은 데이터 품질 *플래그·표시·보류*를 보강했습니다. 실시간 데이터 공시 검증이나 포워드 PER 정확성 보장은 아닙니다. 테스트는 오프라인 단위테스트 17건 및 과거 스냅샷 재계산입니다.
