# Ballotpedia API Research for The Ballot Box (Texas Ultralocal Candidate Coverage)

_Last researched: April 8, 2026_

This document summarizes Ballotpedia’s available data interfaces and how they can be integrated into this Django project for upcoming election cycles across Texas, with county-level and address-level focus.

---

## 1) What Ballotpedia offers

Ballotpedia’s data platform is documented at `developer.ballotpedia.org` and is split into two major options:

1. **Geographic APIs** (request/response, JSON over HTTP)
2. **Bulk Data** (daily refreshed downloadable datasets via client portal/API)

### Geographic APIs (best fit for your app UX)

These endpoints are centered on geospatial queries and election lookups:

- `/election_dates` (by point and by optional state/type/year params)
- `/elections_by_point` (candidate + race + ballot-measure data for a lat/long + election date)
- `/elections_by_state` (statewide version, filterable by office level/branch/district type/page)
- `/districts` (districts for a point, optional date for redistricting-aware lookup)
- `/officeholders` (current officeholders by point)

### Bulk Data (best fit for backfills/analytics)

Bulk exports are refreshed every 24 hours and delivered through Ballotpedia’s client portal and a separate API workflow (`getQueryList`, `getQueryResults`). This is useful for:

- Daily warehouse syncs
- Historical analysis snapshots
- Reconciliation jobs against your transactional app DB

---

## 2) Access and operational constraints to plan for

Based on Ballotpedia’s docs, integration planning should assume:

- **API key required** (`x-api-key` header).
- **Package-based field availability** (not every field in docs appears in every package).
- **CORS/domain whitelist constraints** for browser-origin traffic.
- **Rate limiting** uses a token-bucket model (documented as 5 RPS baseline, burst capacity, daily quota).
- **Breaking-change notifications** are communicated in advance, but new fields/endpoints can appear.

### Practical architectural implication

For this project, Ballotpedia calls should be executed **server-side only** (Django/Celery), never directly in browser JS, to avoid CORS and to protect keys.

---

## 3) Texas ultralocal strategy (counties + address-level precision)

To support county-wide and hyperlocal ballots in Texas, use a two-layer strategy:

## Layer A — Address/point-first query flow (primary)

For each user/address:

1. Geocode address to `lat,long`.
2. Call `/election_dates/point` to get relevant election dates around “now”.
3. Call `/elections_by_point` for selected date.
4. Normalize `districts -> races -> candidates` to internal tables.
5. Optionally call `/officeholders` for current office context and continuity UI.

This gives the most accurate “my ballot / near-me races” data, especially in split precinct geographies.

## Layer B — Texas statewide monitoring flow (secondary)

Use `/elections_by_state?state=TX&election_date=...` as a monitoring/backfill feed to:

- detect new races and candidate changes
- monitor completeness (`candidate_lists_complete`)
- fill gaps for localities with low lookup volume

---

## 4) How this maps to your current codebase

Your ingestion architecture already has the right shape for this integration:

- Adapter interface with `fetch` / `normalize`
- Provider registry and provider-specific runs
- Raw payload audit retention (`SourceRecord.payload`)
- Celery tasks for scheduled syncs

### Current Ballotpedia status in repo

- There is a `BallotpediaAdapter`, but it currently reads demo fixture data.
- There is Ballotpedia HTTP code focused on profile/headshot enrichment, not the official geographic election API flow.

### Recommended implementation path (no code change in this document)

1. **Add a real Ballotpedia geographic API client** in `apps/ingestion/http/`.
2. **Upgrade Ballotpedia adapter** to stream:
   - election dates for TX points or county seed points,
   - elections by point/by state,
   - optional officeholders for incumbent context.
3. **Add normalizer(s)** for Ballotpedia race/candidate semantics into canonical models.
4. **Persist source provenance** per entity (provider external IDs, election/race IDs, fetched timestamp).
5. **Schedule staged syncs** in Celery beat:
   - frequent near-term elections,
   - slower historical reconciliations.

---

## 5) Data-model and normalization considerations

Ballotpedia’s dictionary pages emphasize election complexity that should be represented explicitly:

- Multiple election stages for one contest (primary/general/runoff/special).
- Partisan-primary handling can produce multiple race objects distinguished by party/stage context.
- Candidate rows can repeat across party lines in some election structures.
- Redistricting and effective-date logic affect which boundary applies to a race date.

### Internal normalization recommendations

- Store an immutable provider key tuple for dedupe:
  - `(provider, election_id, race_id, candidate_id, stage_party)`.
- Preserve raw arrays like ranked-choice rounds in JSON fields if full normalization is not yet needed.
- Keep explicit `is_complete` / `candidate_lists_complete` flags to control UI badges and data quality states.
- Separate “candidate identity” from “candidacy instance” so the same person can run in multiple stages.

---

## 6) Feature ideas for your Texas-focused application

These are high-value features enabled by Ballotpedia data and aligned with your project goals.

## A. Voter-facing core

- **Address-based sample ballot** for upcoming Texas elections.
- **County election explorer** (all counties, upcoming dates, race counts).
- **Race detail pages** with candidate profiles, party, incumbent/challenger tags.
- **Data freshness indicators** (last sync, completeness status).
- **“What changed since last sync?”** race and candidate diffs.

## B. Editorial/research workflows

- **Completeness dashboard** by county/date (missing candidate lists, partial results).
- **Manual review queue** for identity merges and conflicting attributes.
- **Source payload viewer** for traceability (already aligned with your `SourceRecord` approach).

## C. Advanced civic intelligence

- **Redistricting-aware district timeline** (which boundary applied on election date).
- **Ultralocal alerts** for newly filed candidates in selected TX counties.
- **Contest volatility score** (candidate churn, frequent updates, stage changes).
- **Cross-provider reconciliation** between Ballotpedia and existing Democracy Works ingest.

---

## 7) Proposed rollout plan

## Phase 1 — Validation (1–2 weeks)

- Confirm Ballotpedia package scope for Texas local coverage and required fields.
- Run pilot on a few counties + sample addresses (urban, suburban, rural).
- Define canonical mapping and dedupe rules.

## Phase 2 — Ingestion MVP (2–4 weeks)

- Implement server-side geographic API ingestion.
- Store normalized candidate/race/election records + raw payloads.
- Build sync observability metrics and basic retry/backoff policies.

## Phase 3 — Product features (2–6 weeks)

- Release address-based ballot flow.
- Release county election explorer.
- Add data quality/freshness UI and change-log views.

## Phase 4 — Scale + governance (ongoing)

- Incremental sync tuning by election proximity.
- Quota/rate-aware scheduler tuning.
- QA runbooks for election-week operations.

---

## 8) Risks and mitigations

- **Risk: field variability by package**  
  Mitigation: feature flags + nullable mappings + schema version tagging.

- **Risk: rate limits during high-traffic periods**  
  Mitigation: cache hot queries, precompute county snapshots, queue-based retries.

- **Risk: local race edge cases (special/runoff/party-specific stages)**  
  Mitigation: preserve stage metadata and avoid over-flattening race structures.

- **Risk: CORS/browser direct-call failure**  
  Mitigation: only call Ballotpedia APIs from backend services.

---

## 9) Suggested next implementation tasks in this repo

1. Replace fixture-only Ballotpedia adapter with real API-backed adapter.
2. Add Ballotpedia geographic client (`/election_dates`, `/elections_by_point`, `/elections_by_state`, `/officeholders`).
3. Add Ballotpedia normalizer module parallel to existing provider normalizers.
4. Add management command for TX county/address sync scopes.
5. Add monitoring metrics for API usage, run duration, failure buckets, and completeness.

---

## 10) Primary references consulted

- Ballotpedia Data Client docs home: `https://developer.ballotpedia.org/`
- Geographic APIs getting started
- Geographic endpoints: election_dates, elections_by_point, elections_by_state, districts, officeholders
- Practical guide (sample ballot implementation flow)
- About redistricting
- Rate limiting
- Bulk data download/API docs

