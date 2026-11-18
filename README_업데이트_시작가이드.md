# v0.3.1 업데이트 빠른 안내

1. 압축 해제 후 **안쪽 `ai-quant-asia-garp-research` 폴더**의 내용물을 현재 연구 저장소 루트에 덮어쓰세요. 숨김 `.github` 폴더 포함. 다른 모의운용 저장소는 수정하지 않습니다.
2. GitHub Actions → **Asia GARP Research v0.3.1 — Manual Only** → Run workflow.
3. 첫 실행 권장: `max_symbols=150`, `discover_mode=all5`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`, `evidence_limit=8`.
4. 한국 DART 공식 공시 목록을 자동 수집하려면 GitHub Actions secret `DART_API_KEY`를 별도 등록하세요. 없으면 API 없이 나머지 기능만 실행합니다.
5. 실행 Artifact에서 `24_research_quality_audit.md`, `27_evidence_book.md`, `18_evidence_ledger.csv`, `29_new_discovery_research_queue.csv` 확인.

**주의:** 자동 수집된 뉴스는 헤드라인, 실적은 제공사 원시 값, DART는 공시 목록 링크입니다. 회사의 원문 공시를 대조한 투자 판단은 사용자가 수행하고 `data/research_decisions.csv`에 기록합니다.

**오프라인 테스트**는 실제 인터넷/공시 연계를 검증하지 않습니다. 유니버스가 5개 시장 모두에서 확보되지 않으면 `12_discovery_sources_log.csv` 실패 사유를 확인하세요.
