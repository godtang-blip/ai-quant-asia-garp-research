"""Guard against accidentally publishing multiple active GitHub Actions pipelines.

Archived workflow specifications under docs/ are not executable and remain intact.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'


def test_exactly_one_active_research_workflow():
    active = sorted([*WORKFLOWS.glob('*.yml'), *WORKFLOWS.glob('*.yaml')])
    assert [p.name for p in active] == ['run-research-v05.yml'], (
        'Keep only one v0.5.1 GitHub Actions workflow. '
        'Delete legacy .github/workflows/run-research.yml from the existing repository. '
        f'Active workflows: {[p.name for p in active]}'
    )


def test_v05_workflow_calls_the_integrated_engine():
    script = (WORKFLOWS / 'run-research-v05.yml').read_text(encoding='utf-8')
    assert 'python -m src.v051' in script
    assert 'python -m pytest -q tests' in script
    assert 'src.v031' not in script


def test_v05_reuses_v031_engine_not_a_parallel_workflow():
    v05 = (ROOT / 'src' / 'v051.py').read_text(encoding='utf-8')
    assert 'from .v05 import run as run_v05' in v05
    assert 'meta=run_v05(' in v05
