"""Explicit currency conversion with source/date provenance. No assumed FX values.

Amounts: reporting-currency annual FCF / quote-currency market cap. Capital
stock uses spot; a *period-flow* uses 1y average-rate proxy ONLY when available.
Neither is an IAS 21 financial statement translation or audited normalization.
"""
from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
import math
import pandas as pd

VALID_CURRENCIES = {"USD", "KRW", "JPY", "TWD", "HKD", "CNY"}

@dataclass(frozen=True)
class FXQuote:
    base: str
    quote: str
    spot: float
    period_avg: float | None
    spot_asof: str
    period_from: str
    period_to: str
    source: str

class YahooFX:
    """Fetch 1 unit of currency X priced in USD; cached per run.

    Tries XUSD=X and USDX=X inverse; no fabricated fallback if both fail.
    """
    def __init__(self):
        self.cache: dict[str, FXQuote | None] = {}
        self.log: list[dict] = []

    def to_usd(self, currency: str) -> FXQuote | None:
        currency = str(currency or '').upper().strip()
        if currency == 'USD':
            return FXQuote('USD','USD',1.0,1.0,'IDENTITY','IDENTITY','IDENTITY','IDENTITY')
        if currency not in VALID_CURRENCIES:
            self.log.append({'currency':currency,'status':'UNSUPPORTED_CURRENCY','source':''})
            return None
        if currency in self.cache:
            return self.cache[currency]
        try:
            import yfinance as yf
            for pair, inverse in [(f'{currency}USD=X', False), (f'USD{currency}=X', True)]:
                try:
                    hist = yf.Ticker(pair).history(period='1y', interval='1d', auto_adjust=False)
                    if hist is None or hist.empty or 'Close' not in hist:
                        continue
                    prices = pd.to_numeric(hist['Close'],errors='coerce').dropna()
                    prices = prices[(prices > 0) & prices.map(math.isfinite)]
                    if len(prices) < 5:
                        continue
                    rates = 1.0/prices if inverse else prices
                    last_date = str(prices.index[-1].date())
                    first_date = str(prices.index[0].date())
                    quote = FXQuote(currency, 'USD', float(rates.iloc[-1]), float(rates.mean()),
                                    last_date, first_date,last_date,f'yfinance:{pair}')
                    self.cache[currency] = quote
                    self.log.append({'currency':currency,'status':'FX_PROXY_FOUND','spot':quote.spot,
                        'avg':quote.period_avg,'spot_asof':quote.spot_asof,'period_from':first_date,
                        'period_to':last_date,'source':quote.source})
                    return quote
                except Exception as err:
                    self.log.append({'currency':currency,'status':'PAIR_FETCH_FAILED',
                        'source':f'yfinance:{pair}','detail':type(err).__name__})
        except Exception as err:
            self.log.append({'currency':currency,'status':'FX_LIBRARY_FAILED','detail':type(err).__name__})
        self.cache[currency] = None
        self.log.append({'currency':currency,'status':'FX_UNAVAILABLE','source':''})
        return None


def normalized_values(row: dict, fx: YahooFX) -> dict:
    """Compute USD capitalisation and FCF yield with explicit timestamped FX.

    DCF, accrual definitions and EPS currency are NOT silently harmonized.
    Market cap uses quote/spot; vendor FCF uses 1y avg FX *proxy* where
    vendor's actual FCF reporting period is unknown and a warning is emitted.
    """
    def n(v):
        try:
            v=float(v)
            return v if math.isfinite(v) else math.nan
        except (TypeError, ValueError):
            return math.nan
    quote_currency=str(row.get('currency') or '').upper().strip()
    fin_currency=str(row.get('financial_currency') or '').upper().strip()
    price=n(row.get('current_price'))
    cap=n(row.get('market_cap'))
    fcf=n(row.get('free_cashflow_raw'))
    pfx=fx.to_usd(quote_currency) if quote_currency else None
    ffx=fx.to_usd(fin_currency) if fin_currency else None
    output = {'quote_to_usd':math.nan,'financial_to_usd_avg':math.nan,
        'fx_price_asof':'','fx_source_quote':'','fx_source_financial':'',
        'market_cap_usd':math.nan,'price_usd':math.nan,'fcf_usd_proxy':math.nan,
        'fcf_yield':math.nan,'fx_status':'FX_MISSING_NO_CONVERSION'}
    if pfx:
        output.update({'quote_to_usd':pfx.spot,'fx_price_asof':pfx.spot_asof,
            'fx_source_quote':pfx.source,'market_cap_usd':cap*pfx.spot if cap>0 else math.nan,
            'price_usd':price*pfx.spot if price>0 else math.nan})
    if ffx:
        output['financial_to_usd_avg']=ffx.period_avg if ffx.period_avg else math.nan
        output['fx_source_financial']=ffx.source
        if math.isfinite(fcf) and ffx.period_avg and ffx.period_avg>0:
            output['fcf_usd_proxy']=fcf*ffx.period_avg
    if quote_currency and quote_currency == fin_currency and math.isfinite(fcf) and cap>0:
        output['fcf_yield']=fcf/cap
        output['fx_status']='LOCAL_SAME_CURRENCY_RATIO_VALID_FX_NOT_REQUIRED'
    if pfx and ffx:
        output['fx_status']='FX_CONVERTED_VENDOR_PERIOD_UNVERIFIED'
        if math.isfinite(output['fcf_usd_proxy']) and output['market_cap_usd']>0:
            output['fcf_yield']=output['fcf_usd_proxy']/output['market_cap_usd']
    return output
