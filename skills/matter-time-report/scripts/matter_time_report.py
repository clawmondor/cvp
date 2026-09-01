#!/usr/bin/env python3
"""
Matter Time Report — self-contained script to analyze user time on a CVP matter.

Usage:
    python skills/matter-time-report/scripts/matter_time_report.py <matter_id> [--csv <output_path>]

Requirements:
    railway CLI (logged in), psql, PGPASSWORD in Railway variables

The script:
1. Reads PGPASSWORD from `railway variables`
2. Opens a Railway tunnel to the CVP Postgres DB
3. Detects sessions using a 30-min inactivity gap threshold
4. Outputs per-day, per-user breakdown as CSV and summary text
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], capture=True, timeout=30):
    result = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    if result.returncode != 0 and capture:
        print(result.stderr, file=sys.stderr)
    return result


def get_railway_variables():
    """Read PGPASSWORD and PGHOST/PGPORT from `railway variables --json`."""
    result = run(["railway", "variables", "--json", "--service", "cvp"])
    if result.returncode != 0:
        raise RuntimeError("Failed to read Railway variables. Is the CLI logged in?")
    try:
        vars_ = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse Railway variables JSON: {result.stdout}")

    out = {}
    for var in vars_:
        name = var.get("name") or var.get("key", "")
        val = var.get("value", "")
        if name == "PGPASSWORD":
            out["PGPASSWORD"] = val
        elif name == "PGDATABASE":
            out["PGDATABASE"] = val
    if not out.get("PGPASSWORD"):
        raise RuntimeError("PGPASSWORD not found in Railway variables for service cvp")
    out["PGDATABASE"] = out.get("PGDATABASE", "railway")
    return out


def open_tunnel():
    """
    Start `railway connect Postgres-hobv --tunnel-only` and wait for it to assign
    a local port. Returns the port as an int.
    """
    proc = subprocess.Popen(
        ["railway", "connect", "Postgres-hobv", "--tunnel-only"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    local_port = None
    deadline = time.time() + 30
    pattern = re.compile(r"Port\s+(\d+)", re.IGNORECASE)

    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            # process ended
            break
        m = pattern.search(line)
        if m:
            local_port = int(m.group(1))
            break
        # also check stderr
        err = proc.stderr.readline()
        if err:
            m = pattern.search(err)
            if m:
                local_port = int(m.group(1))
                break
        time.sleep(0.5)

    if local_port is None:
        proc.kill()
        raise RuntimeError(
            "Could not detect tunnel port from railway connect output. "
            "Ensure Railway CLI is logged in and the Postgres plugin is configured."
        )

    return proc, local_port


def run_query(port: int, pgpassword: str, matter_id: str) -> list[dict]:
    """Execute the session-analysis SQL and return rows as dicts."""
    sql = """
    WITH ordered AS (
      SELECT
        al.created_at,
        al.user_id,
        u.email,
        u.display_name,
        LAG(al.created_at) OVER (
          PARTITION BY al.user_id
          ORDER BY al.created_at
        ) AS prev_ts
      FROM audit_logs al
      LEFT JOIN users u ON al.user_id = u.id
      WHERE al.matter_id = %(matter_id)s
    ),
    with_sessions AS (
      SELECT
        created_at, user_id, email, display_name,
        CASE
          WHEN prev_ts IS NULL
               OR (created_at - prev_ts) > INTERVAL '30 minutes'
          THEN 1 ELSE 0
        END AS session_start
      FROM ordered
    ),
    session_groups AS (
      SELECT
        created_at, user_id, email, display_name,
        SUM(session_start) OVER (
          PARTITION BY user_id
          ORDER BY created_at
          ROWS UNBOUNDED PRECEDING
        ) AS grp
      FROM with_sessions
    ),
    session_durations AS (
      SELECT
        user_id,
        email,
        display_name,
        DATE(
          MIN(created_at) AT TIME ZONE 'America/Los_Angeles'
        ) AS day,
        MAX(created_at) - MIN(created_at) + INTERVAL '30 minutes'
          AS session_duration
      FROM session_groups
      GROUP BY user_id, email, display_name, grp
    )
    SELECT
      day,
      COALESCE(display_name, email, 'Unknown') AS user_name,
      COUNT(*)                              AS num_sessions,
      TO_CHAR(SUM(session_duration), 'HH24:MI:SS') AS total_time,
      ROUND(
        SUM(EXTRACT(EPOCH FROM session_duration)) / 3600, 2
      )                                      AS total_hours
    FROM session_durations
    GROUP BY day, COALESCE(display_name, email, 'Unknown')
    ORDER BY day ASC, user_name ASC;
    """

    psql_cmd = [
        "psql",
        f"postgresql://postgres:{pgpassword}@127.0.0.1:{port}/railway",
        "-t", "-A", "-c", sql,
    ]

    result = run(psql_cmd, capture=True)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed:\n{result.stderr}\n{result.stdout}")

    rows = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 5:
            rows.append({
                "day": parts[0].strip(),
                "user_name": parts[1].strip(),
                "num_sessions": int(parts[2].strip()),
                "total_time": parts[3].strip(),
                "total_hours": float(parts[4].strip()),
            })
    return rows


def format_duration(hours: float) -> str:
    h = int(hours)
    m = round((hours - h) * 60)
    return f"{h}h {m}m"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Matter time report — per-day, per-user session analysis"
    )
    parser.add_argument(
        "matter_id",
        help="The UUID of the CVP matter to analyze",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Write results to this CSV file",
    )
    parser.add_argument(
        "--tunnel-only",
        action="store_true",
        help="Open the DB tunnel but do not run the query (for debugging)",
    )
    args = parser.parse_args()

    matter_id = args.matter_id.strip()

    print("Reading Railway variables for service 'cvp'...")
    rail_vars = get_railway_variables()
    pgpassword = rail_vars["PGPASSWORD"]

    print("Opening Railway Postgres tunnel...")
    tunnel_proc, port = open_tunnel()
    print(f"Tunnel open on port {port}")

    if args.tunnel_only:
        print("  --tunnel-only set; stopping here. Press Ctrl-C to close tunnel.")
        try:
            tunnel_proc.wait()
        except KeyboardInterrupt:
            tunnel_proc.kill()
        return

    try:
        print(f"Running session analysis for matter {matter_id}...")
        rows = run_query(port, pgpassword, matter_id)
    finally:
        print("Closing tunnel...")
        tunnel_proc.kill()
        tunnel_proc.wait()

    if not rows:
        print("No audit events found for that matter.")
        return

    # Summary stats
    total_sessions = sum(r["num_sessions"] for r in rows)
    total_hours = sum(r["total_hours"] for r in rows)
    active_days = len({r["day"] for r in rows})
    users = sorted({r["user_name"] for r in rows})

    # Console summary
    print("\n" + "=" * 60)
    print(f"  Matter: {matter_id}")
    print(f"  Active days: {active_days}")
    print(f"  Users: {', '.join(users)}")
    print(f"  Total sessions: {total_sessions}")
    print(f"  Total time: {format_duration(total_hours)} (~{total_hours:.2f} hrs)")
    print("=" * 60)
    print(f"\n{'Date':<14} {'User':<20} {'Sessions':>9} {'Time':>10} {'Hours':>7}")
    print("-" * 64)
    for r in rows:
        print(
            f"{r['day']:<14} {r['user_name']:<20} "
            f"{r['num_sessions']:>9} {r['total_time']:>10} "
            f"{r['total_hours']:>7.2f}"
        )

    # Per-user totals
    from collections import defaultdict
    user_totals: dict = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    for r in rows:
        user_totals[r["user_name"]]["sessions"] += r["num_sessions"]
        user_totals[r["user_name"]]["hours"] += r["total_hours"]

    print("\n  Per-user totals:")
    for u, t in sorted(user_totals.items()):
        print(
            f"    {u:<20} {t['sessions']:>4} sessions  "
            f"{format_duration(t['hours'])} (~{t['hours']:.2f}h)"
        )

    # CSV output
    if args.csv:
        out_path = Path(args.csv).expanduser()
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["Date", "User", "Sessions", "Time (HH:MM:SS)", "Time (Hours)"],
            )
            w.writeheader()
            for r in rows:
                w.writerow({
                    "Date": r["day"],
                    "User": r["user_name"],
                    "Sessions": r["num_sessions"],
                    "Time (HH:MM:SS)": r["total_time"],
                    "Time (Hours)": r["total_hours"],
                })
        print(f"\nCSV written to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
