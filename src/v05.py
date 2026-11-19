"""Run the complete three-stage v0.5 research pipeline, preserving v0.31 lineage.

Stage A: five-market discovery & vendor investigations.
Stage B: source collection + strict analyst-signed official financial reconciliations.
Stage C: analyst-supplied scenarios, counterevidence and investment memos.
No broker / orders / holdings.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import pandas as pd

from .official_universe import OFFICIAL_SOURCE_REGISTRY
from .quality_v051 import SOURCE_KEYS
from .v031 import run as run_v031
from .research_quality import enhance


def run(universe:Path,output:Path,max_symbols:int=150,discover_mode:str='all5_official',
        fx_mode:str='live',delay_seconds:float=1.0,snapshot_csv:Path|None=None,
        per_region:int=90,evidence_mode:str='full',evidence_limit:int=8,
        asof_date:dt.date|None=None, *, markets=None, fetch_vendor=None)->dict:
    if snapshot_csv is not None and discover_mode!='off':
        raise ValueError('Snapshot replay must use --discover-mode off (prevents current-universe lookahead)')
    options = {}
    if markets is not None:
        options['markets'] = markets
    if fetch_vendor is not None:
        options['fetch_vendor'] = fetch_vendor
    meta=run_v031(universe,output,max_symbols,discover_mode,fx_mode,delay_seconds,
                   snapshot_csv,per_region,evidence_mode,evidence_limit, **options)
    # Market registry is not a claim of downloaded/universal coverage.
    logs=pd.read_csv(output/'12_discovery_sources_log.csv',keep_default_na=False)
    rows=[]
    for source in OFFICIAL_SOURCE_REGISTRY:
        entry=source.copy()
        key=SOURCE_KEYS[entry['market']]
        live=logs.loc[logs.source.eq(key), 'status']
        exports=logs.loc[logs.market.eq(entry['market']) & logs.source_kind.eq('PUBLISHER_EXPORT')
                         & logs.status.eq('OK'), 'source']
        entry['retrieval_status']=live.iloc[0] if len(live) else (
            'NOT_REQUESTED' if discover_mode != 'all5_official' else 'NO_LIVE_ADAPTER')
        entry['publisher_exports_imported']='|'.join(exports)
        rows.append(entry)
    pd.DataFrame(rows).to_csv(output/'36_official_exchange_source_registry.csv',index=False,encoding='utf-8-sig')
    # Replay must not use primary reviews submitted AFTER the hypothetical snapshot.
    apply_reviews=not snapshot_csv or asof_date is not None
    quality=enhance(output,universe.parent,asof_date=asof_date,enable_reviews=apply_reviews)
    meta.update(pipeline_revision='0.5',quality_gate=quality,
                official_source_coverage='LIVE_SUPPLEMENTAL_AND_VALIDATED_EXPORTS_SEE_SOURCE_LOG')
    (output/'37_v05_run_manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('v0.5 quality audit: '+json.dumps({k:quality[k] for k in ('screened_n',
          'evidence_checked_n','valuation_reviewed_n','memo_ready_n')},ensure_ascii=False),flush=True)
    return meta


def main():
    p=argparse.ArgumentParser(description='v0.5 research evidence gates, not investment advice')
    p.add_argument('--universe',type=Path,default=Path('data/universe.csv'))
    p.add_argument('--output',type=Path,default=Path('outputs'))
    p.add_argument('--max-symbols',type=int,default=150)
    p.add_argument('--discover-mode',choices=['off','nikkei','regional5','all5','all5_official'],default='all5_official')
    p.add_argument('--fx-mode',choices=['off','live'],default='live')
    p.add_argument('--delay-seconds',type=float,default=1.0)
    p.add_argument('--snapshot-csv',type=Path)
    p.add_argument('--per-region',type=int,default=90)
    p.add_argument('--evidence-mode',choices=['off','news','full'],default='full')
    p.add_argument('--evidence-limit',type=int,default=8)
    p.add_argument('--asof-date',type=dt.date.fromisoformat,default=None,
                   help='Explicit UTC analysis cutoff. Required to apply manual reviews on replay snapshot')
    a=p.parse_args()
    run(a.universe,a.output,a.max_symbols,a.discover_mode,a.fx_mode,a.delay_seconds,
        a.snapshot_csv,a.per_region,a.evidence_mode,a.evidence_limit,a.asof_date)

if __name__=='__main__':main()
