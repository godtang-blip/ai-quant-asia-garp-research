# Pipeline and reproduction

[Project overview](../README.md) · [DB HiTek case](../case-studies/db-hitek/README.md) · [Development trail](AI_DEVELOPMENT_TRAIL.md)

## Pipeline code

| Step | What runs and who reviews it |
|---|---|
| **Collect listings** | [Five-market discovery](../src/discovery_v031.py) and [listing smoke check](../src/discovery_smoke.py). Code records sources, accepted security codes and failures. |
| **Rank research candidates** | [Research screen](../src/v031.py) and [GARP scoring](../src/scoring_v03.py). Code applies industry anchors, metric coverage and quality gates. |
| **Review evidence and valuation** | [Integrated v0.5.1 checks](../src/v051.py), [quality gates and valuation](../src/research_quality.py), and the [quality specification](QUALITY_SPEC_V05.md). The workflow can collect evidence references and apply gates to reviewed inputs. |
| **Make the decision** | The researcher reviews filings, selects assumptions, and records counterevidence and the final judgment. The [DB HiTek PDF](../case-studies/db-hitek/db-hitek-equity-research-2026-11-20.pdf) is a separately prepared report. |

## Local reproduction

Run from the repository root. The default-branch workflow uses Python 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m src.discovery_smoke --output discovery-smoke
```

Use a new output path for each smoke check. Inspect `11_discovery_universe.csv`, `12_discovery_sources_log.csv`, and `47_venue_coverage.csv`. A successful process can still report zero live listings if sources are inaccessible. Tests exercise code behavior and fixtures; fetch success and financial reconciliation have separate evidence.

## GitHub Actions

The [default-branch v0.5.1 workflow](../.github/workflows/run-research-v05.yml) is manually dispatched. Use `discovery_only=true` for listings alone. The [venue guide](FIVE_MARKET_COVERAGE.md) and [China acquisition notes](CHINA_A_SHARE_DISCOVERY.md) cover optional access settings and source scope.

The provided DB HiTek shortlist is an archived v0.3.1 snapshot replay. [PR #2](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/2) covers a separate Gemini experiment and [PR #4](https://github.com/godtang-blip/ai-quant-asia-garp-research/pull/4) covers v0.6 integration. Neither PR is needed for these default-branch commands.

Before sharing outside the private repository, review access, the repository and history for credential and personal data exposure, and permissions to redistribute vendor and exchange data. The original snapshot and full workbook are outside version control.
