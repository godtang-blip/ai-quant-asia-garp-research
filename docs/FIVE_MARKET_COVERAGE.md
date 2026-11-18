# Five-market coverage audit

The v0.5 archive investigated 1,722 securities, including 1,121 Taiwan securities (65.1%). The Taiwan Stock Exchange supplied 1,093 accepted listing rows. Japan's broad JPX file failed and the Nikkei 225 supplied a narrower index. Korea lacked a data.go.kr key, while China and Hong Kong had no exchange connector. The pipeline combined these sources with curated names and capped Yahoo screeners. That gave Taiwan a much larger source list and left the other markets dependent on smaller, differently selected sources. The [original retrospective](V051_RETROSPECTIVE_AUDIT.md) has the observed counts.

## Sources and remaining gaps

| Market | Archived analyzed / eligible | Discovery path | Outstanding coverage or validation |
|---|---:|---|---|
| Korea | 99 / 8 | KRX KOSPI and KOSDAQ API with optional `PUBLIC_DATA_API_KEY`, or dated KRX exports | Cloud had no key. Trading holidays may require `KRX_BASE_DATE`. KONEX is out of scope. |
| Japan | 310 / 54 | JPX English and Japanese workbooks, dated JPX export, and Nikkei 225 as index supplement | Updated parser supports XLS and XLSX, title rows, and supported alphanumeric codes. Cloud proxy blocked publisher requests. Domestic Prime, Standard, and Growth scope excludes foreign shares, ETFs, and REITs. |
| Mainland China | 91 / 11 | Validated imports of SSE, SZSE, and BSE exports, with capped Yahoo sample as supplement | Direct exchange downloads are still unconnected. A missing venue file leaves a gap. Yahoo ticker support and financial data may vary by venue. |
| Hong Kong | 101 / 13 | Validated HKEX export, with capped Yahoo sample as supplement | Direct HKEX download is still unconnected. Publisher security classifications must be carried into the export. |
| Taiwan | 1,121 / 154 | TWSE listed-company JSON, plus optional TWSE and TPEx exports | Cloud proxy blocked TWSE. TPEx requires a dated export. The live TWSE list still needs vendor equity-type confirmation. |

Every accepted source is recorded even if it repeats a curated or already discovered ticker. The curated name and research metadata take precedence for duplicate tickers. Exchange rows establish a listing candidate. Financial fields and security-type confirmation still come through the existing research pipeline. The count is of distinct listed securities by ticker, so two listed classes of an issuer can count twice.

## Reproduce the comparison

Run `src.v051` with `--discover-mode all5_official`. At the default cap of 150, the sampler reserves 15 fetch attempts for each market, or every discovered ticker if fewer than 15 are available. For other positive caps the target is one tenth of the cap rounded down, with a minimum of one. If the cap is smaller than the number of available markets, markets with the fewest discovered names get first access. Unused slots are distributed in proportion to the remaining ticker counts, with whole-slot rounding. A stable hash picks tickers within each market so publisher row order does not determine the sample. Use `--max-symbols 0` for all discovered tickers. Legacy discovery modes retain their original sampling.

Using the archived market counts as a synthetic discovery input, the old proportional design gives Taiwan 98 out of 150 fetch slots. The revised design gives Taiwan 65, Japan 28, and Korea, mainland China, and Hong Kong 19 each. The reserve reduces the effect of uneven source access on the research sample. Actual financial availability and eligibility still depend on each ticker's data and the existing gates.

- `11_discovery_universe.csv` records each ticker and all its source IDs.
- `12_discovery_sources_log.csv` records scope, accepted rows, failures, and imports' source URL, date and normalized-file checksum.
- `38_market_coverage_audit.csv` reports discovered and listing-backed tickers, the sample share and any shortfall against the market target, fetch attempts and successes, rows with at least one finite financial field, scored rows, and candidates that pass the existing screen. A response with no usable financial fields adds to fetch successes only.
- `46_market_stratified_research_queue.csv` lists eligible candidates by market and flags markets that need manual review. Global ranking remains in `01_all_research_candidates.csv`, and `39_market_research_queue.csv` retains both existing lanes for compatibility.
- `45_coverage_comparison.csv` shows the historical analyzed and eligible counts beside the current discovered, selected, financial-observation and eligible counts. It remains available if every fundamental fetch fails. Different source dates and fetch budgets limit direct comparison. The archive lacks a separate financial-observation count.

With identical curated, live-source, and vendor fixture inputs, adding five venue exports expanded discovery from 2 to 6 tickers and listing-backed coverage from 1 to 6. Financial observations were available for 5 of the 6, and 0 passed screening. These are controlled comparisons. No new live five-market coverage percentage has been established.

## Supply publisher exports

Download current exchange files directly and retain the originals. Convert each venue to a UTF-8 CSV in the directory named by `GARP_LISTING_EXPORT_DIR`. For the existing GitHub workflow, set the repository variable of that name to a directory present in the checkout. Supported filenames are `KRX_KOSPI.csv`, `KRX_KOSDAQ.csv`, `JPX.csv`, `SSE.csv`, `SZSE.csv`, `BSE.csv`, `HKEX.csv`, `TWSE.csv`, and `TPEX.csv`.

Use these columns:

```csv
code,company,security_type,as_of,source_url
```

Preserve leading zeros. Use the publisher's effective date and official HTTPS source URL throughout a file. The importer requires a date within 45 days, validates venue and ticker format, rejects duplicate common-stock codes, and accepts only records explicitly typed `COMMON_EQUITY`. Known non-common types (`PREFERRED`, `ETF`, `ETN`, `REIT`, `FUND`, `WARRANT`, `BOND`, `OTHER`) are counted and excluded. Unknown types reject the file. This verifies the file format and provenance metadata. The operator remains responsible for faithful conversion, genuine publisher origin, and complete venue coverage. Failed or missing files are visible in the source log.

## Disclosure verification in v0.5.2

The listing audit gives a future Gemini agent a stable ticker and source trail for resolving issuer identity. Listing provenance stays separate from the existing issuer registry, filing verification queue, and analyst-attested comparisons. An agent can propose filing URLs, dates, page locations and extracted observations for review without changing scoring or automatically promoting candidates through the current evidence and valuation gates. Existing evidence files and schemas are preserved.
