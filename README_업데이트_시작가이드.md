# v0.3 적용 방법 (기존 저장소 업데이트)

1. 이 ZIP을 압축 해제합니다.
2. **안쪽 `ai-quant-asia-garp-research` 폴더의 내용물**을 기존 동명 GitHub 저장소에 복사합니다. `.github/workflows/run-research.yml` 포함. 새 저장소를 만들지 않습니다.
3. Commit 및 Push. 기존 개인 실전/모의 운용 저장소 `ai-quant-v512-paper`에는 복사하지 않습니다.
4. GitHub → Actions → **Asia GARP Research v0.3 — Manual Only** → Run workflow.
5. 권장 최초 설정: `max_symbols=90`, `discover_mode=nikkei`, `fx_mode=live`.
6. 실행 화면의 Artifacts ZIP 내려받아 `03_research_report.md`, `12_discovery_sources_log.csv`, `13_fx_normalization_audit.csv`, `15_cross_industry_scores.csv`를 확인합니다.

**처음부터 모든 기업 분석은 비권장**: `max_symbols=0`은 출처에서 발견한 종목까지 전부 조회해 API 제한에 걸릴 수 있습니다. `90`에서 성공 후 증가시키세요.

새 종목이 0개인 경우 `12_discovery_sources_log.csv`에서 수집 실패 여부를 확인하세요. 초록색 체크만으로 자동 종목 발굴이 성공했다는 뜻은 아닙니다.

일부 수치가 `NaN`이면 환율이나 원자료가 확인되지 않아 보류한 것일 수 있습니다. 임의로 채우지 마세요.

통합 점수는 **정량 심층분석 우선순위**이지, 실제 저평가/초과수익을 검증한 점수가 아닙니다. 공개 전 투자 메모 1건의 공시 원문·재무 기간·환율·기업별 회계기준을 직접 확인하세요.

변경 내역과 실험 한계는 `README.md`, `CHANGELOG.md`, `PORTFOLIO_README_GUIDE.md`를 참고하세요.
