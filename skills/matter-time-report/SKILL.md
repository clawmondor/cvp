# Matter Time Report Skill

Calculate and report time spent by users on a given matter, using CVP audit log data.

## When to use

Use this skill when asked to calculate how much time a user has spent on a specific matter, generate a per-day or per-user time report, or export session data for billing/audit purposes.

## Usage

### Quick one-liner (within an active DB tunnel)

```bash
# Open tunnel first
railway connect Postgres-hobv --tunnel-only
# note the local port Railway assigns (e.g. 53661)

# Then run via psql
PGPASSWORD=<PGPASSWORD> psql "postgresql://postgres@127.0.0.1:<PORT>/railway" -c "
  WITH ordered AS (
    SELECT
      al.created_at,
      al.user_id,
      u.email,
      u.display_name,
      LAG(al.created_at) OVER (PARTITION BY al.user_id ORDER BY al.created_at) AS prev_ts
    FROM audit_logs al
    LEFT JOIN users u ON al.user_id = u.id
    WHERE al.matter_id = '<MATTER_ID>'
  ),
  with_sessions AS (
    SELECT
      created_at, user_id, email, display_name,
      CASE WHEN prev_ts IS NULL OR (created_at - prev_ts) > INTERVAL '30 minutes' THEN 1 ELSE 0 END AS session_start
    FROM ordered
  ),
  session_groups AS (
    SELECT
      created_at, user_id, email, display_name,
      SUM(session_start) OVER (PARTITION BY user_id ORDER BY created_at ROWS UNBOUNDED PRECEDING) AS grp
    FROM with_sessions
  ),
  session_durations AS (
    SELECT
      user_id, email, display_name,
      DATE(MIN(created_at) AT TIME ZONE 'America/Los_Angeles') AS day,
      MAX(created_at) - MIN(created_at) + INTERVAL '30 minutes' AS session_duration
    FROM session_groups
    GROUP BY user_id, email, display_name, grp
  )
  SELECT
    day,
    COALESCE(display_name, email, 'Unknown') AS user_name,
    COUNT(*) AS num_sessions,
    TO_CHAR(SUM(session_duration), 'HH24:MI:SS') AS total_time,
    ROUND(SUM(EXTRACT(EPOCH FROM session_duration))/3600, 2) AS total_hours
  FROM session_durations
  GROUP BY day, COALESCE(display_name, email, 'Unknown')
  ORDER BY day ASC;
"
```

### Standalone Python/Claude Code script

See `scripts/matter_time_report.py` for a self-contained script that:
- Opens the Railway tunnel automatically
- Runs the session analysis query
- Outputs CSV and/or summary text

## How it works

**Session detection:** A new session is counted each time a user's activity resumes after a gap of more than 30 minutes. This threshold is based on typical human attention/break patterns. It is a heuristic, not a hard guarantee of session boundaries.

**Duration estimation:** For each detected session, duration is calculated as `(last_event − first_event) + 30 minutes`. The 30-minute buffer accounts for the fact that the last event timestamp is not the same as the moment the user closed the tab or navigated away.

**Active time only:** This measures *observed activity* (item updates, SERP runs, matter views, crop edits, etc.). Idle time within a tab (browser left open but user away) is not captured — only events that hit the server are recorded.

**Attribution:** Events are attributed to users via `audit_logs.user_id` → `users.id`. Events with no matching user (NULL user_id) are shown as "Unknown" — these may be API tokens or deleted accounts.

**Timezone:** All timestamps are stored in UTC in the database. The query converts to `America/Los_Angeles` (PDT/PST) for display grouping.

## Data sources

- `audit_logs` table — all action events with timestamps, user IDs, and matter IDs
- `users` table — display name and email for human-readable attribution
- Railway logs — currently not used; HTTP-level logs do not include matter/user context

## Fields in output

| Field | Description |
|---|---|
| `day` | Calendar date (PDT/PST) |
| `user_name` | Display name or email, "Unknown" if no user match |
| `num_sessions` | Number of distinct sessions detected that day |
| `total_time` | Total session time formatted as HH:MM:SS |
| `total_hours` | Total session time in decimal hours |
