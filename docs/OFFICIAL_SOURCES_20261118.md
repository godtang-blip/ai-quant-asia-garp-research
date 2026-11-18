# Official source registry (architecture checked on 2026-11-18)

Issuer identity (listing) is not issuer earnings verification. URLs below are publisher documentation/data endpoints, not evidence that a live GitHub runner successfully fetched them.

- Korea: Financial Services Commission / KRX listed securities info: https://www.data.go.kr/en/data/15094775/openapi.do , REST: https://apis.data.go.kr/1160100/GetKrxListedInfoService_V2/getItemInfo_V2 ; needs approved service key. DART issuer filing index separate at https://opendart.fss.or.kr/.
- Japan: JPX listed-issues historical/monthly data page https://www.jpx.co.jp/english/markets/statistics-equities/misc/01.html ; parsed XLSX https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xlsx ; parser currently numeric 4-digit shares only. Separate Nikkei index constituent HTML exists in v0.31.
- Taiwan: TWSE OpenAPI https://openapi.twse.com.tw/ ; listed-company directory https://openapi.twse.com.tw/v1/opendata/t187ap03_L . Not Taipei Exchange OTC.
- Hong Kong: HKEX official securities lists https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en ; no source reader; vendor screener used pending source parsing.
- Mainland China: Shanghai Stock Exchange https://www.sse.com.cn/ and Shenzhen Stock Exchange https://www.szse.cn/ ; no official source reader; vendor screener used pending source parsing.

Licensing, site formats and client access should be checked before publishing output commercially. The software records publisher-source error/status instead of treating fallbacks as official.
