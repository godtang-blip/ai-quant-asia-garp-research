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

## SSE pagination follow-up

The next reported Actions listing-only run discovered **11,051 securities**, with zero new mainland China listings. SSE Main Board and STAR both reached response validation and failed with `INCOMPLETE_PAGINATION`. SZSE workbook reset its connection, SZSE JSON returned HTTP 500, BSE returned HTTP 403, and the BaoStock SDK timed out after 65 seconds.

Inspection of AKShare 1.20.65's `stock_info_sh_name_code` confirmed the uppercase `STOCK_TYPE` filter, `COMPANY_STATUS=2,4,5,7,8`, `type=inParams`, cache-size hint, and top-level `result` array. The SSE adapter now sends those parameters. It supports the prior nested `pageHelp.data` container when `result` is absent, and requires valid publisher totals in either case. It checks requested versus echoed page numbers when available, repeated codes, changing totals, board membership, and the final accepted row count. It stores only allowlisted fields and numeric structural metadata from the first and last pages or from the failing page, without emitting listing rows or response bodies. Look for `response_diagnostics` in `12_discovery_sources_log.csv`.

A direct request with the revised SSE filters to the official query endpoint was blocked by this cloud's proxy at CONNECT 403, before an origin response. Access to the Actions run list was also refused here. The earlier Actions failure cannot be attributed to a particular root cause without genuine response metadata. Fixtures test both array shapes and distinct failure reasons. The next Actions run must establish that each board returns nonzero rows and reconciles its own page totals. A separate comparison with dated exchange totals is still needed to establish scope.

BaoStock now probes its published native TCP endpoint before starting the SDK. The probe has an eight-second subprocess deadline, including DNS, and distinguishes failed name resolution, connection refusal, network errors, and timeout. In this cloud the probe returned `DNS_ERROR`. Whether a GitHub runner can establish TCP remains unknown: a login or query timeout alone does not distinguish failed TCP from an unresponsive SDK session. Imported, dated snapshots do not perform the TCP probe.

For independent fallback research, the previously tested AKShare methods still reuse exchange infrastructure. Tushare Pro's `stock_basic` is a candidate for authorized security-master access, subject to token entitlement and verified active-listing scope for SZSE and BSE. Its public documentation URL was blocked by the cloud proxy during this review, so no adapter or coverage claim was added. Use the existing dated, publisher-validated SZSE and BSE export paths when automated official sources are unavailable. Keep vendor data distinct from publisher exports. [Tushare candidate documentation](https://tushare.pro/document/2?doc_id=25)

## SSE live verification and remaining SZSE/BSE gaps

The latest reported discovery-only GitHub Actions run returned **13,370 unique securities**, including **2,320 mainland China securities**. SSE Main Board accepted **1,700** and STAR accepted **619**. Both publisher totals matched the accepted count on one complete page. The total mainland China count also includes one previously known security. This verifies live retrieval and response-level completeness for both SSE requests. It leaves exchange-scope completeness unverified. The current probe to the SSE market-statistics overview and STAR site was blocked with proxy CONNECT 403. An analyst with approved publisher access should use the same as-of date and compare Main Board A-share and STAR **listed securities** counts, avoiding B shares and separate issuer/market-cap series.

| Route | Live observation | Action or open issue |
|---|---|---|
| SZSE Main Board and ChiNext | Actions workbook connection reset and JSON returned HTTP 500. Cloud official listing page blocked at CONNECT 403. | Use a dated publisher export, or a separately labeled authorized Tushare stock_basic export described below. |
| BSE | Actions official endpoint returned HTTP 403. Cloud listing page blocked at CONNECT 403. | Use a dated publisher export or Tushare export with explicit BSE membership. NEEQ-only records are excluded. |
| BaoStock | The latest Actions run established TCP then exceeded the old 65-second SDK deadline. The cloud listing-only run stopped at its TCP preflight. | Run discovery-only again and inspect the named SDK stage. A dated BaoStock snapshot still bypasses the live network path. |
| Tushare Pro stock_basic | Public documentation and API host probes were blocked at CONNECT 403. No authorized account or actual export was available for validation here. | Use entitled access from an approved environment. The import schema is fixture-tested. Provider status, record scope and totals remain unverified with live data. |
| Eastmoney and CNINFO | Public origin requests were blocked by the cloud proxy. | No independently verified export, listing scope, or automated access basis was established from these routes. |

### Authorized Tushare export

Use the provider's entitled `stock_basic` interface with separate `exchange=SZSE` and `exchange=BSE` queries and `list_status=L`. Before saving, confirm the provider's completed result, board definitions and date from its source, and retain the original response privately if the terms allow. Use `SZSE.csv` and `BSE.csv` with this header:

```csv
as_of,ts_code,symbol,name,exchange,market,list_status,list_date,delist_date
```

Use a single explicit snapshot date (`YYYY-MM-DD`) per file, and keep leading zeros in codes. Keep the provider's `YYYYMMDD` listing dates and leave `delist_date` blank for active records. Use the provider's board fields `主板`, `创业板`, or `北交所` as relevant. The importer requires both Shenzhen boards when importing Shenzhen, rejects mixed exchanges, mismatched ticker suffixes, duplicate codes and dates over seven days old, and separates inactive and unknown rows from accepted records. It validates the file's internal consistency and does not certify the provenance or completeness of an operator-supplied export.

Point `GARP_TUSHARE_EXPORT_DIR` at the directory on an approved runner or local machine and use `discovery_only` (or `python -m src.discovery_smoke --output discovery-smoke`). In Actions the variable must refer to a directory available in the workspace. Transfer data or include it in a checkout only where the provider's terms permit. The workflow receives no Tushare credential. The two files are independent, so an unavailable or invalid export for one exchange leaves the other available. Results appear as `IMPORTED_VENDOR_SNAPSHOT` and third-party security master evidence. Inspect the snapshot date and hash in the source log and board counts in `scope_counts` before using them.

BaoStock's one-shot Linux/macOS SDK worker now allows 8 seconds each for login and trading calendar, and 16 seconds each for security master and dated inventory, with a 52-second overall ceiling after TCP preflight. It makes no automatic retries. The log reports only the last permitted stage name on timeout or failure and omits raw SDK output.

## BaoStock inventory-first diagnostics

The latest inspected Actions discovery-only run again found **13,370 unique securities**. SSE Main Board (1,700), SSE STAR (619), KIND, JPX, HKEX, TWSE and TPEx succeeded. The SZSE workbook reset, its JSON route returned HTTP 500, and BSE returned HTTP 403. BaoStock reached the security-master stage after login and the trading calendar, then exceeded its 16-second deadline. No Tushare snapshots were imported.

The SDK now reads the dated inventory before calling `query_stock_basic()`. The installed SDK receives the initial page in `query_stock_basic()` itself; iterating the result can request additional pages. `12_discovery_sources_log.csv` records `sdk_metrics` with elapsed seconds and available row counts for those two phases separately. It logs only numeric metrics and the failure-stage label. Login, calendar and inventory retain 8-, 8- and 16-second limits. The former combined master limit is split into 12 seconds for the call and 16 for iteration, with a 64-second SDK worker ceiling and a separate eight-second TCP preflight ceiling. The implementation makes no automatic SDK retries.

If the dated inventory returns but the master fails, `48_baostock_provisional_shenzhen.csv` can contain fresh, nonduplicate Shenzhen code candidates from the provider's `sz.` series. The artifact does not establish instrument type, active listing status, or inventory completeness. Every row is explicitly screening-ineligible. These codes are excluded from the discovery universe, coverage totals and financial pipeline. When the master succeeds, the existing inventory/master and eligibility checks still apply. The strict BaoStock capture command and dated snapshot import remain supported.

Select both `discovery_only` and `china_only` in the existing Actions workflow to inspect mainland routes independently, or run `python -m src.discovery_smoke --china-only --output discovery-smoke` locally. The China-only option applies only to discovery-only execution. Inspect the SDK metrics and the separate provisional artifact. BSE remains unresolved and is reported separately. The current cloud run failed BaoStock TCP DNS preflight and publisher CONNECT requests; inventory-first performance and its useful code count remain unverified on Actions.

## Unified China discovery and authorized Tushare API

The same China-only run now emits `49_china_board_coverage.csv` for SSE Main Board, SSE STAR, SZSE Main Board, ChiNext and BSE, and `50_china_source_overlap.csv` for ticker-level source attribution and name disagreements. Existing artifacts retain the deduplicated universe, source diagnostics, and provisional BaoStock quarantine. Board counts require route-specific evidence as well as matching symbol ranges. An unmatched name may reflect an abbreviation or translation. To compare against publisher statistics, pass `--china-benchmarks` with `board,source_id,count,as_of,url,scope_comparable`. A delta is only produced when the source and reference dates match and the scope is explicitly comparable. A vendor observation time does not stand in for a provider as-of date.

The Eastmoney investigation used a single one-row request for each selector against `https://push2.eastmoney.com/api/qt/clist/get`: `m:0+t:6`, `m:0+t:80`, `m:1+t:2`, `m:1+t:23`, and `m:0+t:81+s:2048`. All five probes returned proxy CONNECT 403, with no origin response. The field semantics, Beijing versus NEEQ selection, pagination, freshness and permitted automated access were not established. No Eastmoney adapter was enabled.

Tushare Pro is optional. Set the Actions secret `TUSHARE_TOKEN` only if the account is entitled to `stock_basic` and provider terms permit this use. Discovery-only dispatch requests `exchange=SZSE` and `exchange=BSE` separately, with `list_status=L`. It uses the fixed HTTPS host `api.tushare.pro`, does not follow redirects or retry, and keeps provider error bodies and tokens out of diagnostics. Each response is checked for schema, exchange, board, active listing, duplicate codes and the row ceiling. The provider does not supply a dated count in this adapter; returned counts are third-party observations with provider date and total unverified. The cloud proxy blocked this endpoint and no entitled token was supplied, so transport compatibility, entitlements and actual coverage remain unverified. The optional calls run independently and sequentially to avoid concurrent bursts against an account with unknown limits. The normal Actions research step does not receive this secret.

For a portable BSE acquisition, use an authorized Tushare Pro client or vendor export service from an approved environment. Request `stock_basic(exchange="BSE", list_status="L")` with these provider fields: `ts_code,symbol,name,exchange,market,list_status,list_date,delist_date`. For Shenzhen, run the same query with `exchange="SZSE"`. Retain only provider-supplied fields and append the confirmed effective snapshot date as `as_of`; save UTF-8 `BSE.csv` and `SZSE.csv` preserving six-character codes. Do not substitute retrieval time for an unknown effective date. Verify the completed provider response and usage rights before transferring files, set `GARP_TUSHARE_EXPORT_DIR`, then run `discovery_only` and `china_only`. The importer requires active BSE-board rows, excludes NEEQ-only and delisted rows, validates date and scope independently by file, and records the hash and import classification. The dated publisher export route remains available independently.

In the cloud smoke run for this change, all three exchanges produced zero new live listings; BaoStock failed TCP DNS preflight. No Tushare token or dated export was available. The prior Actions evidence of 1,700 SSE Main Board and 619 STAR live securities remains the verified baseline. This change does not establish live Shenzhen or Beijing coverage.

## Single-run acquisition acceptance

Run the existing Actions workflow on the PR branch with `discovery_only`, `china_only`, and `china_provider_probe` enabled. This run skips financials and has three distinct outcomes:

| Artifact | Interpretation |
|---|---|
| `51_china_provider_probe.csv` | Transport and safe response-shape metadata. An HTTP response, reported total, or recognized set of keys does not establish a usable data source. |
| `49_china_board_coverage.csv` and `12_discovery_sources_log.csv` | Source-specific listing retrieval and accepted rows, with provenance, dates and available completeness checks. |
| `52_china_acquisition_acceptance.csv` | One row each for SZSE Main Board, ChiNext and BSE, showing accepted live vs. imported counts, outstanding external requirements and whether the resulting listings can enter a normal financial fetch. Screening eligibility remains unevaluated. |

The opt-in probe sends an unauthenticated HEAD request to Tushare's HTTPS API host. A reachable transport, including an HTTP method refusal, does not verify `stock_basic` or entitlement. If permitted by the provider, set the repository variable `GARP_EASTMONEY_PROBE_ALLOWED=1` to enable three Eastmoney GET requests (one row per SZSE Main Board, ChiNext and BSE selector). Leave this variable unset unless the operator has confirmed that the intended probe is allowed under applicable terms. Permission, selector semantics, board membership and pagination have yet to be independently established. The workflow does not follow redirects, retry, spoof browser headers, store samples, or add probe results to the universe.

Run paid or authorized acquisition only after confirming the account is entitled to both `stock_basic` queries. The discovery-only run uses the optional repository secret `TUSHARE_TOKEN` if configured. After validating actual retrieval, a normal `all5_official` dispatch can opt in with `enable_tushare_research`. The default is false, and the ordinary research step receives an empty token unless explicitly enabled. These inputs preserve the existing screening and security-type gates. A dated authorized export remains an alternative to credential-based acquisition.

The readiness iteration's cloud test could not reach Tushare through the proxy and had zero accepted listings on each missing board. Eastmoney was skipped because permission was unconfirmed. No authorized SZSE/BSE CSV or token was available. These findings do not establish GitHub runner reachability.
