# Mainland China A-share discovery

**Live outcome remains unresolved.** The latest user-reported GitHub Actions run discovered 11,052 securities across five markets, including 2,590 from Korea KIND. None of its mainland China exchange listing routes succeeded. This change adds an independent BaoStock path and a listing-only Actions dispatch. No run of the new workflow has yet demonstrated broad live mainland China coverage.

## Source-by-source results

The current cloud listing-only probe ran on November 19, 2026 (Korea time). Every route below accepted zero live securities. No payload as-of date, duplicate or exclusion statistics exist for these failures. The generated `12_discovery_sources_log.csv` records the exact UTC attempt time and available status, counts, date, hash, scope, and checks for each source. `47_venue_coverage.csv` separates publisher counts from vendor counts and their overlap.

| Exchange and board | Provider and source | Latest reported Actions | Current cloud probe | Evidence and scope |
|---|---|---|---|---|
| SSE Main Board A | [SSE listing query](https://query.sse.com.cn/sseQuery/commonQuery.do) | Origin HTTP 403 | Proxy CONNECT 403 | Official route; no successful inventory |
| SSE STAR | [SSE listing query](https://query.sse.com.cn/sseQuery/commonQuery.do) | Skipped after Main Board refusal | Skipped after same-host proxy refusal | Official route; no successful inventory |
| SZSE Main Board and ChiNext A | [SZSE report workbook and JSON](https://www.szse.cn/api/report/ShowReport) | Workbook connection reset; JSON HTTP 500 | Workbook proxy CONNECT 403; same-host fallback skipped | Official routes; neither representation verified |
| BSE | [BSE listed-company route](https://www.bse.cn/nqxxController/nqxxCnzq.do) | Origin HTTP 403 | Proxy CONNECT 403 | Official route; no verified BSE inventory |
| SSE / SZSE / BSE separately | [BaoStock](http://www.baostock.com/), SDK at `tcp://public-api.baostock.com:10030` | New route, unrun | SDK login error `10002007`, network receive failure; zero rows | Third-party master. BSE support is unverified; counts appear separately and zero is explicit |
| SSE / SZSE / BSE | AKShare 1.20.65 | No independent source tested | Package code inspected | The three exchange functions call the same official endpoints above; `stock_info_a_code_name` concatenates those functions and the STAR call |
| Candidate alternative | [Eastmoney security-list service](https://push2.eastmoney.com/api/qt/clist/get) | Unverified | One-row probe received proxy CONNECT 403 | Payload scope, freshness, and permitted automated use were not established; no adapter enabled |
| Candidate alternative | [CNINFO](https://www.cninfo.com.cn/) | Unverified | Homepage proxy CONNECT 403 | No independently verified current security master with usable listing-status and instrument metadata; no adapter enabled |

## Vendor validation and next verification

BaoStock's client fetches `query_stock_basic()` and a dated `query_all_stock()` snapshot for the most recent completed trading day in its calendar. The adapter checks both inventories for missing candidate codes, duplicate and conflicting records, stale data, and the availability of Shanghai and Shenzhen records. It maps the provider's exchange identifiers to `.SS`, `.SZ`, and `.BJ`; number ranges then distinguish known A-share series and board groups within those markets. It rejects B-shares, non-stock types, exited securities, and securities that listed after the snapshot. Unknown classifications are counted separately. It records distinct counts for SSE Main Board, STAR, SZSE Main Board, ChiNext, and BSE. These are internal provider consistency checks; no official exchange-level benchmark was available for this probe.

The universe records source identifiers, source-specific company names and name disagreements. A name difference may reflect abbreviation or translation. The venue audit shows official–vendor overlap. Third-party listings retain a separate evidence classification and enter any later financial screen subject to its unchanged security-type checks. No vendor result is recorded as an official listing or confirmed common equity. A dated publisher export remains available for scopes where live automation does not supply listings.

1. In the single research workflow, select this branch and enable `discovery_only`. The dispatch uploads listing artifacts and skips fundamentals, scoring, evidence and valuation.
2. Verify that `baostock_security_master` reports `OK`, a fresh date, a live SDK retrieval mode and substantial actual counts for both Shanghai and Shenzhen. Review BSE independently, even if it reports zero. Compare each board against dated exchange statistics on an authorized network.
3. If BaoStock access fails on GitHub-hosted runners, run the same SDK on an approved network that permits its published TCP endpoint. Run `python -m src.china_security_master > baostock-snapshot.json` there, then verify the exit status. Where provider terms permit transferring the snapshot, make the file available to the runner and set `GARP_BAOSTOCK_SNAPSHOT` to its path. Revalidation and hashing are identical, and the audit labels it imported. For broader or missing BSE coverage, use a dated, reviewed [publisher export](FIVE_MARKET_COVERAGE.md).
4. Keep ordinary research dispatch behavior at its existing default. To include a validated BaoStock listing source in normal official discovery, set the Actions variable `GARP_ENABLE_BAOSTOCK=1`. Continue to treat official exchange totals as a separate scope check.

No official routes, validation gates, or candidate scores were replaced by target counts or quotas.
