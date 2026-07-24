"""One-shot data migration: legacy CVP database -> new ClaimOS database.

Reads the source (legacy CVP schema, `matters`/`matter_id`) READ-ONLY and writes
the target (ClaimOS schema, `claims`/`claim_id`). Run once at cutover after the
target DB is at `alembic upgrade head` and seeded.

Cutover ordering: `alembic upgrade head` runs BEFORE this script and applies the
`c9851834200b` data migration (`migrate_external_claim_access`) against an EMPTY
`claim_access` table, converting 0 rows. This script then copies legacy
`matter_access` rows into `claim_access` (`migrate()`), verifies row-count parity
against the legacy source (`verify_parity` / `raise_on_parity_mismatch`), and
ONLY THEN converts the newly-copied external `claim_access` rows into
`role_grants` (`convert_external_access`, called from `main()`). That ordering
is required: the conversion deletes external `claim_access` rows, which would
make the parity check fail if run first. See `convert_external_access` for
details.
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
    ("items", "items", {"matter_id": "claim_id", "rcv_unit_cents": "retail_unit_cents"}),
    ("comments", "comments", {}),
    ("item_crops", "item_crops", {}),
    ("vision_job_images", "vision_job_images", {}),
    ("vision_runs", "vision_runs", {"matter_id": "claim_id"}),
    ("serp_searches", "serp_searches", {}),
]

# Primary-key column overrides for the Postgres ON CONFLICT target. Every table
# uses `id` except `app_setting`, whose PK is `key` (see models_app_setting.py).
# Verified by checking every model's `primary_key=True` column.
#
# Note on `app_setting` specifically: the Postgres path below is insert-only
# (`ON CONFLICT (key) DO NOTHING`). If `seed`/`bootstrap-admin` already
# populated the target before cutover, any legacy `app_setting` row whose key
# collides with one already present is silently skipped — the target's
# (already-seeded) value wins, not the migrated legacy value.
PK_OVERRIDES: dict[str, str] = {"app_setting": "key"}

# ORM tables that intentionally have NO legacy CVP source and must never appear
# in TABLE_PLAN. These are RBAC v2 tables (see models_grants.py): they are
# populated by a future Alembic *data migration* that converts legacy
# `claim_access` rows into `role_grants` (+ `role_grant_claims` /
# `role_grant_overrides`), not by this one-shot legacy-db copy. Keep this set
# in sync with models_grants.py; it is consumed by
# tests/test_migrate_db.py::test_table_plan_is_fk_safe_topological_order to
# scope the "TABLE_PLAN covers exactly the ORM metadata" invariant down to the
# tables that are actually supposed to be copied.
NO_LEGACY_SOURCE_TABLES: frozenset[str] = frozenset(
    {"role_grants", "role_grant_claims", "role_grant_overrides"}
)


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
        # Legacy `matters` has no nickname; every ClaimOS claim requires a
        # unique, non-null one. Derive a placeholder from the id (specialists
        # rename later). Mirrors the Alembic backfill.
        if target_table == "claims" and not d.get("nickname"):
            d["nickname"] = f"Claim {str(d['id'])[:8]}"
        out.append(d)
    cols = list(out[0].keys())

    # Guard against schema drift: a legacy source column with no counterpart in
    # the target table (after the matter_id->claim_id remap) would otherwise
    # surface as an opaque INSERT error mid-cutover. Fail loudly and early
    # instead, naming the table and the offending column(s).
    target_columns = {c["name"] for c in sa.inspect(tgt.engine).get_columns(target_table)}
    unknown = [c for c in cols if c not in target_columns]
    if unknown:
        raise RuntimeError(
            f"migrate-db: source table '{source_table}' has column(s) {unknown} with no "
            f"counterpart in target '{target_table}' (remapped keys: {cols})"
        )

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


def verify_parity(
    source_url: str,
    target_url: str,
    table_plan: list[tuple[str, str, dict[str, str]]] | None = None,
) -> dict[str, tuple[int, int]]:
    """Post-run parity check (spec §8.2): compare row counts for every
    (source_table -> target_table) pair in TABLE_PLAN.

    Returns a dict keyed by target table name, mapping to (source_count,
    target_count). Does not raise itself — callers (e.g. `main`) decide what
    to do with a mismatch, which keeps this a plain, easily unit-testable
    function. `table_plan` defaults to the full `TABLE_PLAN`; tests may pass a
    subset to check parity against a schema that only has some tables.
    """
    plan = TABLE_PLAN if table_plan is None else table_plan
    src_eng = sa.create_engine(source_url)
    tgt_eng = sa.create_engine(target_url)
    counts: dict[str, tuple[int, int]] = {}
    with src_eng.connect() as src, tgt_eng.connect() as tgt:
        for target_table, source_table, _renames in plan:
            source_count = src.exec_driver_sql(f"SELECT count(*) FROM {source_table}").scalar_one()
            target_count = tgt.exec_driver_sql(f"SELECT count(*) FROM {target_table}").scalar_one()
            counts[target_table] = (source_count, target_count)
    return counts


def raise_on_parity_mismatch(counts: dict[str, tuple[int, int]]) -> None:
    """Raise a clear RuntimeError if any table's source/target counts differ.

    Split out from `verify_parity` so both halves (compute vs. enforce) are
    independently unit-testable.
    """
    mismatched = {table: st for table, st in counts.items() if st[0] != st[1]}
    if mismatched:
        detail = "; ".join(
            f"{table} (source={source}, target={target})"
            for table, (source, target) in mismatched.items()
        )
        raise RuntimeError(f"migrate-db: row-count parity check failed for: {detail}")


def convert_external_access(target_url: str) -> int:
    """Convert freshly-copied external `claim_access` rows into `role_grants`.

    Cutover ordering (see module docstring / README): `alembic upgrade head` runs
    the `c9851834200b` data migration against an EMPTY `claim_access` table (0
    rows converted), and only THEN does `migrate-db` copy legacy `matter_access`
    rows into `claim_access` — including external users' rows. Those freshly
    copied external rows are never converted by the alembic migration (it already
    ran), and the RBAC v2 resolver (`dependencies._external_effective_role`) reads
    only `role_grants` for external users, so without this step every external
    user is locked out (403) post-cutover with an inert `claim_access` row.

    This must be called AFTER `raise_on_parity_mismatch` succeeds — the
    conversion deletes external `claim_access` rows, and the parity check
    compares legacy `matter_access` counts against `claim_access` counts. Running
    the conversion first would make a correct migration look like a parity
    failure.
    """
    from sqlalchemy.orm import Session

    from claimos.migrate_claim_access import migrate_external_claim_access

    engine = sa.create_engine(target_url)
    with Session(bind=engine) as session:
        return migrate_external_claim_access(session)


def main() -> None:
    source = os.environ["LEGACY_DATABASE_URL"]
    target = os.environ["DATABASE_URL"]
    counts = migrate(source, target)
    total = sum(counts.values())
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print(f"migrated {total} rows across {len(counts)} tables")

    parity = verify_parity(source, target)
    for table, (source_count, target_count) in parity.items():
        print(f"  parity {table}: source={source_count} target={target_count}")
    raise_on_parity_mismatch(parity)
    print("parity check passed: source and target row counts match for all tables")

    # Must run AFTER the parity check (see convert_external_access docstring):
    # converts the just-copied external claim_access rows into role_grants so
    # external users aren't locked out post-cutover.
    converted = convert_external_access(target)
    print(f"converted {converted} external claim_access row(s) to role_grants")


if __name__ == "__main__":
    main()
