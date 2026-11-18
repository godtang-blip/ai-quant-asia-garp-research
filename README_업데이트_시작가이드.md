# Asia GARP v0.5 — One Workflow, Three Research Stages

1. Back up your current `ai-quant-asia-garp-research` repository and extract the full v0.5 ZIP. Copy the **contents of the inner repository directory**, including `.github/`, onto the existing repo root.
2. **Important upgrade cleanup:** in the existing local repo delete `.github/workflows/run-research.yml` (obsolete v0.3.1 GitHub Actions workflow). Keep `.github/workflows/run-research-v05.yml`. Copying the new ZIP over old files will not remove the obsolete one automatically. Do not delete `src/v031.py`; it is still used internally by v0.5.
3. In GitHub Desktop, commit **all v0.5 code/doc changes and the deletion of the old workflow**, then Push origin. Avoid Force Push.
4. GitHub → **Actions → Asia GARP v0.5 | Discovery + Evidence + Valuation (Research Only)** → **Run workflow**. Recommended first run: `max_symbols=150`, `discover_mode=all5_official`, `per_region=90`, `fx_mode=live`, `evidence_mode=full`. This single invocation executes all three research stages.
5. In the run's **Artifacts**, inspect `34_research_quality_v05.json`, `35_quality_upgrade_comparison.md`, `32_research_stage_gate.csv`, and `33_analyst_memoranda.md`.
6. `MEMO_READY=0` is expected until you manually reconcile primary filings and enter reviewed valuation inputs. Optional repository Secrets: `PUBLIC_DATA_API_KEY` for Korea listed-company identity adapter; `DART_API_KEY` for Korean regulator filing index.

Only the v0.5 Actions workflow should remain active. The archival v0.3.1 specification stays in `docs/v031-legacy-workflow.yml.txt` for history. Test success verifies process safeguards, not investment outperformance.
