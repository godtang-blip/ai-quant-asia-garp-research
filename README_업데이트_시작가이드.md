# Asia GARP v0.5 — GitHub 1회 통합 실행 안내

1. 기존 `ai-quant-asia-garp-research` 저장소를 백업하고 이번 ZIP 안쪽의 같은 이름 폴더에 있는 내용을 덮어쓴 다음 GitHub Desktop에서 Commit → Push 합니다. 숨김 `.github` 폴더도 포함하세요. **별도 모의운용 저장소는 수정하지 않습니다.**
2. GitHub 저장소 → **Actions** → **Asia GARP v0.5 | Discovery + Evidence + Valuation (Research Only)** → **Run workflow**.
3. 최초 권장: `max_symbols=150`, `discover_mode=all5_official`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`. 모두 한 번에 실행합니다.
4. 완료한 Run 페이지 아래 **Artifacts**에서 `asia-garp-v05-...zip`을 다운로드합니다. 우선 `34_research_quality_v05.json`, `35_quality_upgrade_comparison.md`, `32_research_stage_gate.csv`, `33_analyst_memoranda.md`, `12_discovery_sources_log.csv`를 보세요.
5. **초기 `MEMO_READY=0`은 정상**입니다. 기존 v0.31의 공식 공시 재무수치 실제 대조가 0건이었습니다. 임의로 인증한 것으로 처리하지 않습니다. 특정 기업에 대해 3개 핵심 재무수치를 직접 공시와 대조한 뒤 `data/verified_financials.csv`에 기록하고, `data/valuation_assumptions.csv`, `data/research_decisions.csv`를 작성한 후 재실행해야 단계가 승격됩니다.
6. 한국의 공식 KRX 상장목록을 자동 확인하려면 공공데이터포털에서 API 접근을 발급받아 Actions Secret `PUBLIC_DATA_API_KEY`를 등록하세요. 한국의 DART 공시 **목록**은 별도 `DART_API_KEY`를 등록해야 합니다. 두 기능 모두 키가 없어도 다른 시장 연구는 실행합니다.

**품질검증:** `python -m pytest -q tests`를 GitHub Actions에서 선행 실행합니다. CI 성공 = 시스템 동작 확인이지 투자분석 정확도나 미래 수익률 향상 입증은 아닙니다.
