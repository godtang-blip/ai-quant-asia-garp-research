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


def test_dispatch_modes_are_literal_strings_forwarded_to_cli():
    from ast import literal_eval
    import re

    script = (WORKFLOWS / 'run-research-v05.yml').read_text(encoding='utf-8')
    for mode, expected in {
        'discover_mode': ['all5_official', 'all5', 'regional5', 'nikkei', 'off'],
        'evidence_mode': ['full', 'news', 'off'],
        'fx_mode': ['live', 'off'],
    }.items():
        match = re.search(rf'^      {mode}:\n((?:        .*\n)+)', script, re.M)
        assert match
        options = re.search(r'^        options: (.+)$', match[1], re.M)
        assert options and literal_eval(options[1]) == expected
        env = 'GARP_INPUT_' + mode.upper()
        assert f'{env}: ${{{{ inputs.{mode} }}}}' in script
        assert f'--{mode.replace("_", "-")} "${env}"' in script


def test_listing_only_dispatch_skips_research_and_quality_steps():
    script = (WORKFLOWS / 'run-research-v05.yml').read_text(encoding='utf-8')
    assert 'discovery_only:' in script
    assert 'if: ${{ inputs.discovery_only }}' in script
    assert script.count('if: ${{ !inputs.discovery_only }}') == 2
    assert 'python -m src.discovery_smoke --output outputs' in script


def test_normal_tushare_requires_explicit_input():
    script = (WORKFLOWS / 'run-research-v05.yml').read_text(encoding='utf-8')
    integrated = script.split('      - name: Integrated three-stage research / no orders')[1].split(
        '      - name: Listing discovery only')[0]
    assert "TUSHARE_TOKEN: ${{ inputs.enable_tushare_research && secrets.TUSHARE_TOKEN || '' }}" in integrated


def test_private_bundle_is_opt_in_and_only_validated_paths_reach_research():
    script = (WORKFLOWS / 'run-research-v05.yml').read_text(encoding='utf-8')
    assert "if: ${{ inputs.use_private_listing_bundle }}" in script
    assert "vars.GARP_LISTING_ARTIFACTS_ALLOWED" in script
    assert "--jq '.private'" in script
    assert 'persist-credentials: false' in script
    assert script.count("GARP_VALIDATED_CHINA_PUBLISHER_DIR: ${{ steps.listing_bundle.outputs.publisher_dir }}") == 2
    assert script.count("GARP_VALIDATED_CHINA_VENDOR_DIR: ${{ steps.listing_bundle.outputs.vendor_dir }}") == 2
    assert '53_china_import_validation.json' in script
