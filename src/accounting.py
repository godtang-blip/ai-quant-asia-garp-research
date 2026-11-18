"""Issuer-level accounting disclosure ledger, never inferred as audited by country.

No automatic IFRS 'restatement' from opaque vendor ratios. Analyst evidence
must contain BOTH document URL and filing date to mark an issuer as reviewed.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

EXPECTED_HINTS={
 'Korea':'K-IFRS typical; verify issuer filing',
 'Japan':'J-GAAP / IFRS / JMIS / US GAAP possible; verify issuer',
 'Taiwan':'Taiwan-endorsed IFRS typical; verify issuer',
 'Hong Kong':'HKFRS / IFRS / PRC ASBE depending issuer; verify',
 'China':'PRC ASBE common; verify issuer',
}

def issuer_evidence(csv_path:Path)->dict:
    if not csv_path.exists():return {}
    df=pd.read_csv(csv_path,dtype=str).fillna('')
    expected={'ticker','reported_standard','source_url','filing_date','verified_by'}
    if not expected<=set(df.columns):raise ValueError('Accounting evidence CSV missing fields')
    if df.ticker.duplicated().any():raise ValueError('Duplicate accounting evidence ticker')
    result={}
    for _,r in df.iterrows():
        if r.reported_standard and r.source_url.startswith('https://') and r.filing_date and r.verified_by:
            result[str(r.ticker)]={'standard':r.reported_standard,'source':r.source_url,
                'date':r.filing_date,'reviewer':r.verified_by}
    return result


def accounting_basis(ticker,market,evidence:dict)->dict:
    doc=evidence.get(str(ticker))
    if doc:
        return {'reported_accounting_standard':doc['standard'], 'gaap_evidence_url':doc['source'],
            'gaap_evidence_date':doc['date'],'gaap_reviewed_by':doc['reviewer'],
            'gaap_comparability_status':'STANDARD_IDENTIFIED_NOT_RESTATED_TO_IFRS',
            'jurisdiction_accounting_hint':EXPECTED_HINTS.get(str(market),'Issuer filing must be checked')}
    return {'reported_accounting_standard':'UNKNOWN_PRIMARY_FILING_REQUIRED',
        'gaap_evidence_url':'','gaap_evidence_date':'','gaap_reviewed_by':'',
        'gaap_comparability_status':'NOT_REVIEWED_NO_AUTO_IFRS_RESTATEMENT',
        'jurisdiction_accounting_hint':EXPECTED_HINTS.get(str(market),'Issuer filing must be checked')}
