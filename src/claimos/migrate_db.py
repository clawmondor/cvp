"""One-shot data migration: legacy CVP database -> new ClaimOS database.

Reads the source (legacy CVP schema, `matters`/`matter_id`) READ-ONLY and writes
the target (ClaimOS schema, `claims`/`claim_id`). Run once at cutover after the
target DB is at `alembic upgrade head` and seeded.
"""

from __future__ import annotations

import os

import sqlalchemy as sa

# (target_table, source_table, {source_col: target_col})
# Identity rows have source==target and no column renames. Only the claim rename
# differs. Ordered so parents are inserted before children (FK-safe).
TABLE_PLAN: list[tuple[str, str, dict[str, str]]] = [
    ("groups", "groups", {}),
    ("users", "users", {}),
    ("app_setting", "app_setting", {}),
    ("categories", "categories", {}),
    ("vision_models", "vision_models", {}),
    ("claims", "matters", {}),
    ("claim_access", "matter_access", {"matter_id": "claim_id"}),
    ("rooms", "rooms", {"matter_id": "claim_id"}),
    ("item_groups", "item_groups", {"matter_id": "claim_id"}),
    ("items", "items", {"matter_id": "claim_id"}),
    ("item_crops", "item_crops", {}),
    ("evidence_files", "evidence_files", {"matter_id": "claim_id"}),
    ("vision_runs", "vision_runs", {"matter_id": "claim_id"}),
    ("vision_jobs", "vision_jobs", {"matter_id": "claim_id"}),
    ("vision_job_images", "vision_job_images", {}),
    ("serp_searches", "serp_searches", {}),
    ("comments", "comments", {}),
    ("feedback", "feedback", {}),
    ("feedback_comments", "feedback_comments", {}),
    ("audit_logs", "audit_logs", {"matter_id": "claim_id"}),
    ("refresh_tokens", "refresh_tokens", {}),
]


def _copy_table(
    src: sa.engine.Connection,
    tgt: sa.engine.Connection,
    target_table: str,
    source_table: str,
    renames: dict[str, str],
) -> int:
    rows = src.exec_driver_sql(f"SELECT * FROM {source_table}").mappings().all()
    if not rows:
        return 0
    out = []
    for row in rows:
        d = {renames.get(k, k): v for k, v in dict(row).items()}
        out.append(d)
    cols = list(out[0].keys())
    collist = ", ".join(cols)
    params = ", ".join(f":{c}" for c in cols)
    # upsert-by-PK so a failed run is re-runnable
    tgt.execute(
        sa.text(f"INSERT OR REPLACE INTO {target_table} ({collist}) VALUES ({params})")
        if tgt.dialect.name == "sqlite"
        else sa.text(
            f"INSERT INTO {target_table} ({collist}) VALUES ({params}) ON CONFLICT (id) DO NOTHING"
        ),
        out,
    )
    return len(out)


def migrate(
    source_url: str, target_url: str, only_tables: list[str] | None = None
) -> dict[str, int]:
    src_eng = sa.create_engine(source_url)
    tgt_eng = sa.create_engine(target_url)
    counts: dict[str, int] = {}
    with src_eng.connect() as src, tgt_eng.begin() as tgt:
        for target_table, source_table, renames in TABLE_PLAN:
            if only_tables is not None and target_table not in only_tables:
                continue
            counts[target_table] = _copy_table(src, tgt, target_table, source_table, renames)
    return counts


def main() -> None:
    source = os.environ["LEGACY_DATABASE_URL"]
    target = os.environ["DATABASE_URL"]
    counts = migrate(source, target)
    total = sum(counts.values())
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print(f"migrated {total} rows across {len(counts)} tables")


if __name__ == "__main__":
    main()
