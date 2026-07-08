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
# differs. Ordered so parents are inserted before children (FK-safe). The order
# below matches `claimos.models.Base.metadata.sorted_tables` (a topological sort
# of the target ClaimOS FK graph) — do not reorder by hand; regenerate from
# `sorted_tables` if the schema changes. Source-side names are legacy CVP names
# (`matters`, `matter_access`) but ordering is governed by the TARGET graph.
TABLE_PLAN: list[tuple[str, str, dict[str, str]]] = [
    ("categories", "categories", {}),
    ("groups", "groups", {}),
    ("users", "users", {}),
    ("app_setting", "app_setting", {}),
    ("audit_logs", "audit_logs", {"matter_id": "claim_id"}),
    ("claims", "matters", {}),
    ("feedback", "feedback", {}),
    ("refresh_tokens", "refresh_tokens", {}),
    ("vision_models", "vision_models", {}),
    ("claim_access", "matter_access", {"matter_id": "claim_id"}),
    ("feedback_comments", "feedback_comments", {}),
    ("item_groups", "item_groups", {"matter_id": "claim_id"}),
    ("rooms", "rooms", {"matter_id": "claim_id"}),
    ("vision_jobs", "vision_jobs", {"matter_id": "claim_id"}),
    ("evidence_files", "evidence_files", {"matter_id": "claim_id"}),
    ("items", "items", {"matter_id": "claim_id"}),
    ("comments", "comments", {}),
    ("item_crops", "item_crops", {}),
    ("vision_job_images", "vision_job_images", {}),
    ("vision_runs", "vision_runs", {"matter_id": "claim_id"}),
    ("serp_searches", "serp_searches", {}),
]

# Primary-key column overrides for the Postgres ON CONFLICT target. Every table
# uses `id` except `app_setting`, whose PK is `key` (see models_app_setting.py).
# Verified by checking every model's `primary_key=True` column.
PK_OVERRIDES: dict[str, str] = {"app_setting": "key"}


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
    # SQLite: upsert-by-PK so a failed run is re-runnable. Postgres: insert-only
    # (DO NOTHING on conflict) — not a true upsert, but re-runnable since existing
    # rows are simply skipped. Conflict target is the table's actual PK column.
    pk = PK_OVERRIDES.get(target_table, "id")
    tgt.execute(
        sa.text(f"INSERT OR REPLACE INTO {target_table} ({collist}) VALUES ({params})")
        if tgt.dialect.name == "sqlite"
        else sa.text(
            f"INSERT INTO {target_table} ({collist}) VALUES ({params}) "
            f"ON CONFLICT ({pk}) DO NOTHING"
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
