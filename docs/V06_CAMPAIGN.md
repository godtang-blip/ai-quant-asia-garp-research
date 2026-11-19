# One-click Asia GARP campaign

Use the existing research workflow and PR #4 branch. The campaign restores the frozen discovery plan and durable financial checkpoints before it reserves a new request. Every financial wave publishes the same SQLite checkpoint format consumed by Batch and Aggregate. The frozen listing records, shard names, provider pin and existing terminal results are preserved.

## Start after the completed Batch

1. In GitHub Actions, open the **latest completed successful Batch** for cycle `44456766424` on `codex/garp-v06-integrated-research`. Record its numeric run ID from the run URL. Confirm that its `garp-cycle-44456766424-state-1` and `garp-cycle-44456766424-report-1` artifacts are present. The reported baseline is 16,671 discovered tickers, 200 cumulative vendor attempts, 199 stored financial responses, 183 scored securities and 19 preliminary eligible securities. Keep all the artifacts. The controller checks the frozen plan hash and requires the cumulative checkpoint to account for the published Batch attempts before planning new work.
2. Confirm there are no active or queued **Batch**, **Aggregate** or **Autopilot** runs for this cycle. Use the existing cycle concurrency lock and let each bounded wave finish. Make sure the existing financial-provider allowance has room for 10 more ticker attempts in the current UTC budget window. If the previous Batch used the allowance, start after the next UTC reset.
3. In **Actions → Asia GARP research workflow → Run workflow**, select branch `codex/garp-v06-integrated-research`. Submit these inputs once.

| Input | Value |
| --- | --- |
| `cycle_mode` | `autopilot` |
| `cycle_state` | `44456766424` |
| `max_symbols` | Completed Batch run ID from step 1 |
| `financial_budget` | `5` per wave |
| `cycle_market` | `All` |
| `report_limit` | `3` |
| `filing_budget` | `3` |
| `enable_gemini` | `true` |
| `gemini_max_documents` | `1` |
| `gemini_max_requests` | `3` |

Leave other inputs at their defaults. Autopilot uses the existing `max_symbols` field for the run ID because the workflow already uses all 25 GitHub dispatch inputs. It restores frozen data from all five markets and prepares filing inputs automatically. When the first wave reports `CONTINUE_READY`, the workflow dispatches the second wave using the same workflow file, explicitly targeting the PR branch. It submits the previous run ID, checks for pending research runs and pins the campaign to the starting commit. The workflow file already exists on the default branch for GitHub's workflow dispatch registration. The continuation job requests `actions: write` for its repository-issued `GITHUB_TOKEN`. If repository or organization policy denies dispatch, GitHub records the error and the completed checkpoint and report remain usable.

### Repository variables and secrets

| Repository Variable | Value for the canary |
| --- | --- |
| `GARP_ALLOW_FINANCIAL_CHECKPOINT_ARTIFACTS` | `1` when provider terms permit the existing checkpoint artifacts |
| `GARP_CYCLE_DAILY_BUDGET` | Existing authorized UTC daily limit, with headroom for 10 new attempts |
| `GARP_CAMPAIGN_TOTAL_BUDGET` | `10` |
| `GARP_CAMPAIGN_MAX_RUNS` | `3` |
| `GARP_CAMPAIGN_MAX_HOURS` | `24` |
| `GARP_CYCLE_REQUEST_DELAY` | `2` seconds |
| `GARP_CAMPAIGN_CONTROL` | Empty or `run` |
| `GARP_GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `GARP_GEMINI_INPUT_PRICE`, `GARP_GEMINI_OUTPUT_PRICE` | Existing confirmed USD per million tokens for that model |
| `GARP_GEMINI_MAX_COST_USD` | `0.25` |
| `GARP_GEMINI_TOTAL_INPUT_BUDGET`, `GARP_GEMINI_TOTAL_OUTPUT_BUDGET` | `100000`, `3072` |
| `GARP_GEMINI_TIMEOUT_SECONDS` | `90` |
| `GARP_GEMINI_DIAGNOSTIC_CANARY` | `0` for this campaign |
| `GARP_EDINET_INDEX_DATES` | Keep the already working EDINET dates, or leave empty to use the bounded existing search |
| `GARP_CLASSIFICATION_REGISTRY` | Optional existing repository CSV with dated source and review records |

Use the existing **Repository Secrets** `EDINET_API_KEY` and `GEMINI_API_KEY` for live Japanese filings and Gemini. `DART_API_KEY` enables the existing Korean annual filing index route. Configure secrets in **Settings → Secrets and variables → Actions**. The workflow records missing or inaccessible evidence in the artifacts.

### Request and spending limits

- The canary reserves up to **10 new financial ticker attempts**, 5 per wave and one worker. Each attempt allows at most 8 transport operations, with up to 2 redirects per operation. The conservative HTTP upper bound is 240 transactions across both waves, alongside the existing ledger of ticker attempts. Normal financial retry history is capped at three attempts per ticker, including attempts from prior Batches. A confirmed rate limit or failed authentication stops the financial wave.
- The campaign reads the JPX industry workbook through up to 3 existing publisher URLs once. One dossier evidence round schedules up to 3 issuers. For Japan this means at most 20 EDINET index dates plus up to 3 requests per Japanese issuer, as many as 29 requests. The Korean automatic route uses up to one DART issuer map and one index request per Korean issuer. It records the annual original as requiring review when the original or annual period is unverified.
- Gemini is limited to one document, 3 generation requests including retries, one metadata preflight, the configured token reservations and a **USD 0.25** estimated reservation cap. The manifest records provider-reported usage and extraction response counts. Billing remains subject to the provider's actual usage charges.

## Read the final artifact and continue safely

In the final wave, download **`garp-campaign-44456766424-<run_id>`**. Open `74_campaign_summary.md` for the campaign status and `74_campaign_manifest.json` for quota, checkpoint, provider and evidence results. The package also includes:

- `75_campaign_security_audit.csv` with issuer-level source labels, confidence, conflict evidence, before/after rank and eligibility on the same financial snapshot, weights, valuation anchors, rejection reasons and period flags.
- `76_campaign_industry_mapping.csv` with the explicit campaign overrides and broad labels requiring corroboration. The baseline provisional mappings remain in `src/v031.py`.
- `77_campaign_wave.csv` with the new reservations, market and industry strata, per-security outcomes and observed financial transport counts.
- `79_campaign_exchange_evidence.json` when JPX industry metadata was attempted. Fresh rows must match a frozen official exchange ticker and issuer name. The source date and publisher URL are retained when present.
- `research/73_campaign_preliminary_shortlist.csv` and, when selected for evidence work, `research/71_research_dossiers/index.json`. The shortlist preserves the score rank and records its separate diversified research order. Later full-sweep waves reference the earlier dossier package by evidence run ID.
- `research/63_gemini_evidence.json` for the evidence wave. A positive `extraction_responses_received` and a source-linked dossier finding are required to substantiate live Gemini extraction. Use the official filing records and reconciliation audit to verify figures separately.

`AUTO_CLASSIFIED` denotes an explicit vendor mapping for an equity. `PROVISIONAL` denotes exploratory evidence. `CONFLICTED` and `UNRESOLVED` carry no inferred peer group. Only documented analyst review produces `HUMAN_REVIEWED`. A conflicting classification also blocks the final memo gate. Industry review, numerical provenance, analyst valuation inputs and the final investment thesis are separate requirements.

For a larger campaign, use the same start procedure with `cycle_mode=autopilot-full-sweep` and an explicit `GARP_CAMPAIGN_TOTAL_BUDGET`. Allow enough bounded waves and time for your provider allowance. The controller prioritizes unattempted tickers across five markets, stratifies by available industry labels and preserves retries and successful terminal results. It pauses on daily quota exhaustion, retry backoff or provider blocks. To continue after those pauses, wait until the condition clears, set `GARP_CAMPAIGN_CONTROL=run`, and use the same workflow with `cycle_mode=autopilot-resume` and the latest campaign wave run ID in `max_symbols`. The original campaign settings are carried forward. An expired plan or changed branch commit blocks continuation.

To expand a finished research-now campaign into full-sweep, use its final campaign run ID in `max_symbols` in place of the Batch run ID. The new financial allocation continues from the same checkpoints, counts earlier reservations in the shared daily limit and carries the existing evidence package forward.

To pause or cancel safely, set `GARP_CAMPAIGN_CONTROL=pause` or `cancel` and let the current bounded wave finish. The next wave reads the control before making calls. For an already paused run, use the same resume action to record the cancellation. If a failed wave published a lease but lost its report, an explicit resume restores any durable successful observations, excludes attempts with unknown outcomes from future campaign work and holds evidence calls whose completion cannot be established. Use the manifest to see those security-level blocks. Avoid the GitHub **Re-run jobs** button for checkpoint work.
