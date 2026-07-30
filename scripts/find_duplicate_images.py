#!/usr/bin/env python3
"""
Find duplicate uploaded images (and their items) in a matter by:
  1. md5sum every file in /app/data/uploads that belongs to the matter
  2. Group by hash → files with same hash = duplicate uploads
  3. Cross-reference with evidence_files and items tables
  4. Write duplicate items to a CSV report

Usage:
    # Locally (uploads dir only accessible on Railway):
    uv run python scripts/find_duplicate_images.py

    # On Railway (volume mounted at /app/data):
    railway run --service cvp -- python scripts/find_duplicate_images.py
"""

import csv
import hashlib
import os
from collections import defaultdict
from pathlib import Path

import psycopg2

# ── Config ──────────────────────────────────────────────────────────────────
MATTER_ID = "f3261279-b7e6-4f13-aad1-39802098ab60"
UPLOADS_DIR = "/app/data/uploads"          # Railway container volume path
OUTPUT_CSV = "duplicate_items_from_duplicate_images.csv"


# ── Helpers ──────────────────────────────────────────────────────────────────
def pg_connect():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        # Local dev fallback
        db_url = "postgresql://postgres:password@localhost/railway"
    return psycopg2.connect(db_url)


def md5sum(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    conn = pg_connect()
    conn.autocommit = True
    cur = conn.cursor()

    # 1. Get all evidence file records for this matter
    cur.execute("""
        SELECT id, filename, stored_path, mime_type, size_bytes
        FROM evidence_files
        WHERE matter_id = %s
        ORDER BY filename
    """, (MATTER_ID,))
    evidence_rows = cur.fetchall()
    print(f"Evidence files in matter: {len(evidence_rows)}")

    evidence_by_id = {r[0]: r for r in evidence_rows}

    # 2. md5sum files on disk
    #    stored_path = /app/data/uploads/<evidence_file_id>/<filename>
    hash_to_evidence_ids: dict[str, list[str]] = defaultdict(list)
    missing_files: list[tuple[str, str]] = []

    for ev_id, filename, stored_path, mime, size in evidence_rows:
        disk_path = stored_path   # absolute path on the container filesystem
        if not os.path.exists(disk_path):
            missing_files.append((ev_id, disk_path))
            continue

        try:
            file_hash = md5sum(disk_path)
            hash_to_evidence_ids[file_hash].append(ev_id)
        except Exception as exc:
            print(f"  ERROR hashing {ev_id} ({filename}): {exc}", file=sys.stderr)

    if missing_files:
        print(f"Files not found on disk (skipped): {len(missing_files)}")

    # 3. Find duplicate hashes
    dup_hashes = {h: ids for h, ids in hash_to_evidence_ids.items() if len(ids) > 1}
    print(f"\nDuplicate image groups (same md5): {len(dup_hashes)}")
    for h, ids in dup_hashes.items():
        print(f"  hash={h}  count={len(ids)}")
        for ev_id in ids:
            r = evidence_by_id.get(ev_id, (ev_id, "?", "?"))
            print(f"    [{ev_id}] {r[1]}")

    if not dup_hashes:
        print("No duplicate images found.")
        conn.close()
        return

    # 4. Get items linked to duplicate evidence files
    all_dup_evidence_ids = []
    for ids in dup_hashes.values():
        all_dup_evidence_ids.extend(ids)

    cur.execute("""
        SELECT ic.item_id, ic.evidence_file_id,
               i.description, i.line_number,
               i.rcv_total_cents, i.confirmed, i.excluded, i.matter_id
        FROM item_crops ic
        JOIN items i ON i.id = ic.item_id
        WHERE ic.evidence_file_id = ANY(%s)
        ORDER BY i.line_number
    """, (all_dup_evidence_ids,))
    item_rows = cur.fetchall()
    print(f"\nItems linked to duplicate-image evidence files: {len(item_rows)}")

    # 5. Write CSV
    fieldnames = [
        "duplicate_image_hash",
        "evidence_file_id",
        "evidence_filename",
        "item_id",
        "item_description",
        "item_line_number",
        "item_rcv_total_cents",
        "item_confirmed",
        "item_excluded",
        "item_matter_id",
        "notes",
    ]

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for img_hash, ev_ids in dup_hashes.items():
            for ev_id in ev_ids:
                r = evidence_by_id.get(ev_id, (ev_id, "", ""))
                ev_file_id, filename = r[0], r[1]

                items_for_ev = [row for row in item_rows if row[1] == ev_id]
                if items_for_ev:
                    for (item_id, _, desc, ln, rcv, confirmed, excluded, mid) in items_for_ev:
                        writer.writerow({
                            "duplicate_image_hash": img_hash,
                            "evidence_file_id": ev_file_id,
                            "evidence_filename": filename,
                            "item_id": item_id,
                            "item_description": desc,
                            "item_line_number": ln,
                            "item_rcv_total_cents": rcv,
                            "item_confirmed": confirmed,
                            "item_excluded": excluded,
                            "item_matter_id": mid,
                            "notes": "",
                        })
                else:
                    writer.writerow({
                        "duplicate_image_hash": img_hash,
                        "evidence_file_id": ev_file_id,
                        "evidence_filename": filename,
                        "item_id": "",
                        "item_description": "",
                        "item_line_number": "",
                        "item_rcv_total_cents": "",
                        "item_confirmed": "",
                        "item_excluded": "",
                        "item_matter_id": "",
                        "notes": "no items linked to this evidence file",
                    })

    print(f"\nCSV written: {OUTPUT_CSV}")

    # Summary
    dup_item_ids = set(r[0] for r in item_rows)
    print(f"\n=== Summary ===")
    print(f"Duplicate image groups: {len(dup_hashes)}")
    print(f"Total duplicate evidence files: {len(all_dup_evidence_ids)}")
    print(f"Items tied to duplicate images: {len(item_rows)}")
    print(f"Unique items tied to duplicate images: {len(dup_item_ids)}")

    conn.close()


if __name__ == "__main__":
    import sys
    main()
