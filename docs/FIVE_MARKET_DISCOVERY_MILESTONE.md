# Five-market discovery milestone

**Product status: unresolved.** The prior run figures below were supplied by the user. Its row-level artifacts were unavailable for this review. A focused discovery-only run in this cloud attempted official sources and a one-row Yahoo screener request per market. The proxy returned CONNECT 403 on direct publisher probes. Yahoo could not establish a session. KRX credentials were absent and no publisher exports were supplied. The current run returned zero external securities and retained the 61 curated entries.

| Market | Prior analyzed | Curated carried into current probe | New live listings in current probe |
|---|---:|---:|---:|
| Korea | 99 | 19 | 0 |
| Japan | 3,686 | 22 | 0 |
| Mainland China | 91 | 1 | 0 |
| Hong Kong | 101 | 14 | 0 |
| Taiwan | 1,121 | 5 | 0 |
| Total | 5,098 | 61 | 0 |

The earlier run had 4,800 scored and 589 initially eligible securities overall. The current probe did not fetch financials or screen candidates. These columns measure different stages and should not be subtracted to infer coverage change. The report retains separate discovered, fetched, financial-observation, scored and eligible counts.

## Venue strategy and next actions, in impact order

1. **Mainland China.** Run the new SZSE A-share workbook adapter on a runner that can reach the official SZSE report endpoint. Validate headers, security classes and dated A-share totals with SZSE before counting it as broad coverage. The SSE stock list and statistics page and the BSE listed company page were all blocked at the tunnel. For SSE/BSE use dated official publisher exports through the existing importer when available. These exports are validated as inputs only. No live SSE or BSE adapter was established. If an approved runner can reach the publishers, inspect the official workbook or API and add automation for both venues. B-share or foreign counters cannot be inferred from A-share scope.
2. **Korea.** Obtain authorized data.go.kr KRX listed-issues access and set repository secret `PUBLIC_DATA_API_KEY`. Use `KRX_BASE_DATE` with a known trading day if the default prior weekday is a holiday. The ingestion rejects inconsistent pagination, missing page rows and duplicated issue identities. The official KIND download was also blocked in this cloud. Use validated KOSPI and KOSDAQ exports separately if the API is unavailable. Later add the KIND route only after verifying its security-type and issuer-versus-issue scope against the publisher.
3. **Hong Kong.** Run the new HKEX workbook adapter on an approved runner. The official securities listing page and workbook URL were both blocked here. Compare Main Board and GEM equity scope and source date with HKEX market statistics. Prefer a dated approved HKEX export if the workbook endpoint or schema changes. The parser preserves distinct security codes and excludes categories outside the configured equities scope.
4. **Taiwan.** Preserve TWSE ingestion and validate the new TPEx public company-disclosure JSON endpoint on the approved runner. TPEx is separate from TWSE. The TPEx company list does not cover the Emerging Stock Board. Use dated TPEx publisher exports if the endpoint fails.
5. **Japan.** Preserve JPX workbook and Nikkei index handling. Compare JPX domestic Prime, Standard and Growth scope with the dated exchange table. Keep the Nikkei index and capped Yahoo results labeled as narrower discovery.

For cloud validation, allow the required destination hosts in the environment network settings. For GitHub Actions, use a runner with authorized access to the respective exchange endpoints and rerun the single existing workflow. A cloud CONNECT refusal says nothing about the origin or access from Actions. If the automated sources still fail there, place reviewed exports in an available checkout directory, set the repository variable `GARP_LISTING_EXPORT_DIR`, and follow the format in [the export guide](FIVE_MARKET_COVERAGE.md). No validated alternative feeds beyond the previously supported screened/vendor sample and publisher-export paths were verified live.

The existing workflow writes `47_venue_coverage.csv` during official discovery, including when later fundamentals fail. `12_discovery_sources_log.csv` records path, failure reason where classified, time, and for new sources the payload hash, scoped rows and exclusions. `python -m src.discovery_review ARTIFACTS REVIEW_DIR` creates separate reports. An optional `--benchmarks` CSV uses `venue,source_id,count,as_of,url,scope_comparable`. Enter only independently reviewed official dated figures for the same listing class. Count deltas require matching published source dates and explicit scope alignment. Where a source exposes no as-of date or benchmark is missing, the delta stays blank. A count match never establishes completeness. No comparably scoped official benchmark was retrieved here.

## Candidate follow-up

The review CLI preserves ranks, scores, original flags and decisions, and separates fundamental failures from recoverable missing data, classification, type or quality issues. `korea_investigation_queue.csv` is independent of global rankings. `named_korea_review.csv` reports on NAVER and HD Hyundai Electric when their rows are present. Neither company's latest exclusion can be attributed without the 5,098-security run’s `01_all_research_candidates.csv` and optionally the stage gate. Obtain the completed workflow artifact and run the review command on it.

For corrected data, rerun the unchanged research engine with the validated input data and comparable selection, configuration and cutoffs; then pass its output with `--reassessed-artifacts`. The comparator preserves the before/after values and flags additions/removals separately. Automatic refresh/reassessment from newly corrected source data, dedicated staleness policy and issuer-level reconciliation are pending. The review tooling does not edit gates, analyst decisions or Gemini inputs.
