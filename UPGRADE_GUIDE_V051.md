# Asia GARP Research v0.5.1 — GitHub Upgrade Guide

This is a **full replacement repository snapshot**, not a patch-only ZIP. Preserve the existing Git history and do not create a second repository.

1. In GitHub Desktop, **Fetch origin / Pull origin** in `ai-quant-asia-garp-research` when the working tree is clean. If a merge is unfinished, finish that merge first; do not use Force Push.
2. Unzip the v0.5.1 distribution. Copy the contents of the inner `ai-quant-asia-garp-research/` directory into the root of the existing local repository. Confirm Windows shows the hidden `.github/` directory; allow overwrite.
3. Inspect `.github/workflows/`. Keep exactly **`run-research-v05.yml`**. Delete any leftover `.github/workflows/run-research.yml` from older releases. Do not add a second v0.5.1 `.yml`.
4. Inspect GitHub Desktop Changes: preserve `data/research_decisions.csv`, `data/verified_financials.csv`, and `data/valuation_assumptions.csv` if you have manually added reviewed data since the previous install. The packaged CSVs are intentionally blank and should **not** overwrite your own signed research. When in doubt, skip overwriting the three templates.
5. Commit as `Upgrade Asia GARP to v0.5.1 (coverage and evidence audits)` and **Push origin**.
6. In GitHub open **Actions → Asia GARP v0.5.1 | 5 Markets + Evidence + Valuation (Research Only) → Run workflow**. Start with `max_symbols=150`, `discover_mode=all5_official`, `per_region=90`, `evidence_mode=full`, `fx_mode=live`.
7. Confirm tests pass. Download `asia-garp-v051-<run-id>` from Artifacts; open `42_research_readiness_v051.json`, `38_market_coverage_audit.csv`, `12_discovery_sources_log.csv`, `43_quality_diagnostics_v051.md`, then `32_research_stage_gate.csv`.

**Meaning of the warning:** `PARTIAL_COVERAGE` is expected until official listings are retrieved for all desired markets. This is a research completeness warning, not proof that the code failed. The Actions job may still show success while that warning is present. JPX live parsing will only be confirmed from its own official source log.

**No secrets required** for regular vendor runs. Korean KRX requires `PUBLIC_DATA_API_KEY`; Korean OpenDART filing-index access additionally requires `DART_API_KEY`. Never commit these secrets into files.

**Important:** The older separate paper-trading repository and any brokerage/crypto account are not connected to this project. No orders are generated.
