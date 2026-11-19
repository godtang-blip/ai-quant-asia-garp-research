"""Asia GARP v0.5.1: single-run v0.5 + source coverage and entity audit.

Retains v0.31 screen and v0.5 strict financial stage gates. No live trading.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
from .v05 import run as run_v05
from .quality_v051 import coverage_audit, enhance_v051
from .v031 import FundamentalsUnavailable


def run(universe:Path,output:Path,max_symbols:int=150,discover_mode:str='all5_official',
        fx_mode:str='live',delay_seconds:float=1.0,snapshot_csv:Path|None=None,
        per_region:int=90,evidence_mode:str='full',evidence_limit:int=8,
        asof_date:dt.date|None=None, *, markets=None, fetch_vendor=None)->dict:
    options = {}
    if markets is not None:
        options['markets'] = markets
    if fetch_vendor is not None:
        options['fetch_vendor'] = fetch_vendor
    try:
        meta=run_v05(universe,output,max_symbols,discover_mode,fx_mode,delay_seconds,
                     snapshot_csv,per_region,evidence_mode,evidence_limit,asof_date, **options)
    except FundamentalsUnavailable as exc:
        coverage_audit(output, discover_mode, failed_fetches=exc.attempts)
        raise
    audit=enhance_v051(output,universe.parent,discover_mode)
    meta['pipeline_revision']='0.5.1'
    meta['v051_market_evidence_quality']=audit
    (output/'44_v051_run_manifest.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
    print('v0.5.1 market quality: '+json.dumps({k:audit[k] for k in
          ('market_coverage_status','dominant_market','dominant_market_share_pct',
           'news_quarantined_n','reviewed_investment_memo_n')},ensure_ascii=False),flush=True)
    return meta


def main():
    p=argparse.ArgumentParser(description='Asia GARP v0.5.1 research only; no trading')
    p.add_argument('--universe',type=Path,default=Path('data/universe.csv'))
    p.add_argument('--output',type=Path,default=Path('outputs'))
    p.add_argument('--max-symbols',type=int,default=150,
                   help='0=all discoverable; may require many hours and provider rate limits')
    p.add_argument('--discover-mode',choices=['off','nikkei','regional5','all5','all5_official'],default='all5_official')
    p.add_argument('--fx-mode',choices=['off','live'],default='live')
    p.add_argument('--delay-seconds',type=float,default=.7)
    p.add_argument('--snapshot-csv',type=Path)
    p.add_argument('--per-region',type=int,default=90)
    p.add_argument('--evidence-mode',choices=['off','news','full'],default='full')
    p.add_argument('--evidence-limit',type=int,default=8)
    p.add_argument('--asof-date',type=dt.date.fromisoformat,default=None)
    a=p.parse_args()
    run(a.universe,a.output,a.max_symbols,a.discover_mode,a.fx_mode,a.delay_seconds,
        a.snapshot_csv,a.per_region,a.evidence_mode,a.evidence_limit,a.asof_date)

if __name__=='__main__':main()
