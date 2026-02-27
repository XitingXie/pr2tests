# TODO: Persistent Data Storage for Report Dashboard

## Problem

The current report data storage has limitations:

1. **GitHub Actions cache is ephemeral** — expires after 7 days of no access, 10GB total limit. If cache is evicted, all historical reports are lost.
2. **No queryable history** — can't trend "pass rate for Screen X over the last month" or aggregate across reports programmatically.
3. **No cross-report aggregation** — each report is independent; there's no unified view of all analyzer results over time.
4. **Data lives in CI** — no durable source of truth outside the cache.

## Recommended Solution: Git Branch Storage

Commit report JSON and HTML directly to the `gh-pages` branch instead of using cache + `deploy-pages`.

### Why

- Data is permanent (it's in git history)
- GitHub Pages serves it directly — no extra infrastructure
- JSON files are accessible via URL for future tooling
- Cache becomes unnecessary
- Free, zero maintenance

### Implementation Steps

- [ ] **Modify `dashboard.yml` workflow** — replace cache + `upload-pages-artifact` + `deploy-pages` with direct git commit to `gh-pages` branch
  - Checkout `gh-pages` branch (or create it if it doesn't exist)
  - Copy new report files into the branch
  - Commit and push
  - GitHub Pages auto-deploys from the branch
- [ ] **Add `.nojekyll` file** to `gh-pages` branch so GitHub doesn't process HTML through Jekyll
- [ ] **Handle concurrent pushes** — use `git pull --rebase` before pushing to avoid conflicts when multiple PRs merge quickly
- [ ] **Retention on the branch** — periodically prune old reports from the branch to keep repo size manageable (the `report_index.apply_retention()` already handles this, just need to also commit the deletions)
- [ ] **Migration** — one-time: copy any existing cached reports into the branch

## Future Enhancements (Lower Priority)

These build on top of git branch storage and can be done later:

- [ ] **SQLite summary database** — a single `reports.db` committed to `gh-pages` with one row per report for fast queries. Updated by the workflow after each report generation. Enables trend charts without parsing individual JSON files.
- [ ] **Trend charts in dashboard** — use the SQLite DB (or aggregated JSON) to render pass-rate-over-time, screens-affected-over-time, etc. as inline SVG or Canvas charts.
- [ ] **API endpoint** — expose `index.json` and per-report `report.json` as a lightweight API. Clients can fetch `https://<user>.github.io/pr2tests/index.json` to list all reports and drill into any one.
- [ ] **Webhook notifications** — post to Slack/Teams when pass rate drops below a threshold, or when a new screen is affected for the first time.
- [ ] **External DB migration** — if the repo grows too large from accumulated reports, migrate to Supabase/Firebase with the same schema. The reporter module's `ReportData` dataclass and `asdict()` serialization make this straightforward.

## Decision Log

| Option | Durability | Queryable | Complexity | Cost | Verdict |
|--------|-----------|-----------|------------|------|---------|
| Git branch (`gh-pages`) | Permanent | File-based | Low | Free | **Recommended** |
| GitHub Actions cache | 7 days | No | Low | Free | Current (temporary) |
| GitHub Releases | Permanent | No | Low | Free | Good for snapshots, not continuous |
| SQLite in artifact | 90 days | SQL | Medium | Free | Good add-on to git branch |
| External DB (Supabase) | Permanent | Full SQL | High | Free tier | Overkill for now |
