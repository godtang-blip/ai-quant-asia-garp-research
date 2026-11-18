# Asia GARP v0.2 — GitHub 업데이트 방법

1. 현재 `ai-quant-asia-garp-research` **Private** 저장소를 그대로 사용하세요.
2. `asia_garp_research_v02_full_repo.zip` 압축 해제 후 `ai-quant-asia-garp-research` 내부의 **파일과 `.github` 폴더**를 기존 저장소에 **덮어쓰세요**.
3. GitHub Desktop으로 커밋·Push하거나, 웹에서 변경된 파일을 업로드하세요. **기존 v5.12/모의매매 저장소에는 적용하지 않습니다.**
4. Actions → `Asia GARP Research v0.2 — Manual Only` → Run workflow → `max_symbols`에 `12` 입력 → 초록 체크 확인.
5. 성공 시 Actions 실행 페이지 하단 **Artifacts → `asia-garp-research-v02-...`** 클릭.
6. `03_research_report.md`, `05_data_quality_review.csv`, `06_peer_coverage.csv` 순서로 확인하고, 전체 ZIP을 대화에 올려주세요.
7. 데이터 오류가 없다면 다음엔 `24`로 실행하세요. 24개면 서로 다른 8개 산업을 최소 3종목씩 포함합니다.

**중요:** 초록 체크는 실행 완료이지 금융 데이터 정확성이나 투자 적합성 검증을 의미하지 않습니다. 주가/재무 수치의 보고기간과 공시 출처는 별도 점검이 필요합니다.
