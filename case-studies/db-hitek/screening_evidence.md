# DB HiTek screening and valuation evidence

[Case summary](README.md) · [Research report PDF](db-hitek-equity-research-2026-11-20.pdf) · [Machine-readable evidence and SHA-256 hashes](screening_evidence.json)

## Screening record

- The supplied run metadata records **November 19, 2026, 08:40:34.760288 UTC (17:40:34.760288 KST)**, `pipeline_revision=0.3.1`, `data_mode=SNAPSHOT_REPLAY_NOT_LIVE`, and `discovery_mode=off`.
- The watchlist contains **16,671** codes, comprising 61 curated and 16,610 previously discovered. The source fields record `fetched_n=16671` and `fetch_failures_n=16171`. Their difference gives **500 usable stored financial records**. It does not count live network calls. The metadata records **439** scored securities.
- The supplied shortlist CSV contains **10 rows**, matching `shortlist_n=10`. The Markdown run report displays 15 candidates in its preview table. The preview and exported shortlist have different scopes.
- The CSV order shows **TSMC (2330.TW) first at 80.55** and **DB HiTek (000990.KS) second at 77.15**. DB HiTek has 90% score coverage and is marked `CURATED_LIST` and `is_new_discovery=false`. The source Markdown displays scores to one decimal; the case PDF uses the precise CSV values.
- Source limitations include `filing_verification=NOT_PERFORMED_ON_PRIMARY_STATEMENTS`, `memo_verified_ready_n=0`, `actual_trades=NONE`, `expected_return_backtest=NOT_PERFORMED`, and `score_calibration=NOT_PERFORMED`. The supplied replay files do not identify an exact code commit or Actions run ID. The replay is separate from the [live listing-only milestone](../../docs/FIVE_MARKET_DISCOVERY_MILESTONE.md).

## Report and model reconciliation

| Item | Evidence and scope |
|---|---|
| Company disclosures | The PDF and workbook cite the November 12 IR release for Q3 2026 consolidated sales of **KRW 403.4 billion** and operating profit of **KRW 90.0 billion**, up 14% and 7% year over year. The report flags different growth rates in the broker note (+8% and +12%) and leaves the definitions unreconciled. The original IR and DART pages could not be independently rechecked in the review environment. |
| 2030 sales | **KRW 1.8 trillion** is management's foundry target. **KRW 1.5925 trillion** is the researcher's rounded model estimate. |
| Price and dates | The PDF and workbook cite **KRW 68,500** as the November 20, 2026 close and point to different quote sites. The exchange close could not be independently rechecked. The DCF assumes a December 31 valuation date and uses September 30 parent financial assets and shares. |
| Partial value | PDF page 7 and workbook cells `v15_Decision_Bridge!L17:L19` agree at **KRW 59,458 / 67,254 / 73,851** after rounding. The arithmetic differences to the report-cited close are **−13.2% / −1.8% / +7.8%**. The report sets no target price. |
| Research decision | **Watch. Defer initiating a position.** The calculation awaits independent WACC, terminal capex and reinvestment checks, plus an economic reconciliation of operating cash requirements, subsidiaries, non-controlling interests and the exchangeable bond. |

The report cites the issuer's [Q3 release](https://www.dbhitek.com/kr/media/news/view/2789), [Corporate Value-up Plan](https://www.dbhitek.com/files/551/2026_Corporate_Value_Up_Plan_DB_HiTek_KR.pdf), [DART quarterly filing](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261113001333), and a [KB Securities note](https://kbthink.com/securities-view.html?docId=20261112194633533K). The PDF cites [Kokstock](https://www.kokstock.com/stock/item.asp?item_cd=000990) for its close and the workbook cites [Investing.com](https://kr.investing.com/equities/dongbu-hitek-historical-data).

### Independent arithmetic check

The workbook's 2027–2031 foundry FCFF inputs are 1,232.9432 / 2,878.5144 / 3,251.6246 / 3,361.1837 / 3,468.0247, all in KRW 100 million. The shared inputs are 2032 NOPAT of 2,735.1887 in the same units and 2% terminal growth. The terminal-year cash flow uses `NOPAT × (1 − g / RONIC)`. Discount that perpetuity as `FCFF2032 / (WACC − g) / (1 + WACC)^5`. The conditional equity bridge adds September 30 parent net liquid financial assets of 4,574.1596 (KRW 100 million), sets the contribution of subsidiaries to zero in the illustration, and divides by 42,626,920 shares excluding treasury stock.

| Case | WACC | RONIC | Foundry EV (KRW 100m) | Partial value per share (KRW) |
|---|---:|---:|---:|---:|
| Bear | 12.50% | 8.6% | 20,771 | 59,458 |
| Base | 11.64% | 15.0% | 24,094 | 67,254 |
| Bull | 10.80% | 20.0% | 26,906 | 73,851 |

Assumptions and outputs above were checked against the workbook's stored values and independently recomputed. The January-to-September financial disclosure and the later closing price are cited evidence with separate verification status. The estimates do not establish a complete shareholder valuation.

## Provenance and disclosure

[The JSON excerpt](screening_evidence.json) preserves selected metadata, the first two rows in the source shortlist order, the derived replay success count, DCF inputs and independently checked outputs. It lists the source filenames, timestamp and SHA-256 hashes. The PDF is the supplied original, byte for byte. The original shortlist, Markdown run report and full audit workbook stay outside Git because they contain vendor data or internal notes.
