# v0.5.1 retrospective audit of the submitted v0.5 run

**Input:** User-supplied `asia-garp-v05-44291455708(1).zip` (Nov 18, 2026). This is a static re-audit of v0.5 results, not a new live JPX/universe run.

| Market | Analyzed | Screen-eligible | Official source status in original run |
|---|---:|---:|---|
| Taiwan | 1,121 | 154 | TWSE official listing accepted 1,093 |
| Japan | 310 | 54 | JPX parser failed; Nikkei index succeeded |
| Hong Kong | 101 | 13 | Official exchange adapter not implemented |
| Korea | 99 | 8 | KRX data.go.kr API key missing |
| China | 91 | 11 | Official exchange adapters not implemented |
| **Total** | **1,722** | **240** | **PARTIAL_COVERAGE** |

The 65.1% Taiwan share reflects a **discovery-source and sampling asymmetry**. It does not show that Taiwan has higher expected returns. Source-side counts are not full market censuses.

`quality_v051.enhance_v051()` on the archived v0.5 result produced:

- `market_coverage_status`: `PARTIAL_COVERAGE`.
- `dominant_market`: Taiwan; `dominant_market_share_pct`: 65.1% of discovered names.
- 16 news headlines, of which **4 were quarantined** on conservative title-only identity matching. Three or fewer false-negative decisions could be possible for issuer names with generic words. Headlines were not article-verified.
- One news item attached to `9911.HK` instead named Huitongda Network (`9878.HK`) and was quarantined.
- 30 high-scoring but screening-ineligible issuers entered a *recheck queue*, not auto-promoted to investable names.
- Primary official financial numeric verifications: 0 machine verified; no validated analyst memo or alpha claim.

**What this does not prove:** the live JPX Excel parser is working at the exchange today; China/Hong Kong full-listed-issuer access is fixed; the new classification rules improve future excess returns; any investment claim is verified. A live GitHub run is required for source-level integration verification.
