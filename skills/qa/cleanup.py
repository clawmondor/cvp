"""
Standalone cleanup script — removes all QA test data from the database.

Identifies test data by the QA_ prefix convention used by the data factory:
  - users with email starting "qa_"
  - groups with name starting "QA_"
  - matters with firm_name starting "QA_"
  - related rows (matter_access, items, rooms, evidence_files, comments)

Safe to run at any time. Does not delete physical upload files from data/uploads/.

Usage:
  uv run python skills/qa/cleanup.py
  uv run python skills/qa/cleanup.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove all QA_ prefixed test data")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be deleted without deleting"
    )
    args = parser.parse_args()

    from cvp.db import SessionLocal
    from cvp.models import EvidenceFile, Item, Matter, Room
    from cvp.models_access import MatterAccess
    from cvp.models_auth import Group, User

    db = SessionLocal()
    try:
        # Find QA users and matters
        qa_users = db.query(User).filter(User.email.like("qa_%@qa.local")).all()
        qa_user_ids = [u.id for u in qa_users]

        qa_matters = db.query(Matter).filter(Matter.firm_name.like("QA_%")).all()
        qa_matter_ids = [m.id for m in qa_matters]

        qa_groups = db.query(Group).filter(Group.name.like("QA_%"), Group.kind == "external").all()
        qa_group_ids = [g.id for g in qa_groups]

        # Count related rows
        access_count = (
            db.query(MatterAccess)
            .filter(
                (MatterAccess.user_id.in_(qa_user_ids))
                | (MatterAccess.matter_id.in_(qa_matter_ids))
            )
            .count()
            if (qa_user_ids or qa_matter_ids)
            else 0
        )

        item_count = (
            db.query(Item).filter(Item.matter_id.in_(qa_matter_ids)).count() if qa_matter_ids else 0
        )

        file_count = (
            db.query(EvidenceFile).filter(EvidenceFile.matter_id.in_(qa_matter_ids)).count()
            if qa_matter_ids
            else 0
        )

        room_count = (
            db.query(Room).filter(Room.matter_id.in_(qa_matter_ids)).count() if qa_matter_ids else 0
        )

        print("QA data found:")
        print(f"  {len(qa_users)} users")
        print(f"  {len(qa_groups)} external groups")
        print(f"  {len(qa_matters)} matters")
        print(f"  {access_count} matter_access rows")
        print(f"  {item_count} items")
        print(f"  {file_count} evidence_file records")
        print(f"  {room_count} rooms")

        if args.dry_run:
            print("\nDry run — nothing deleted.")
            return

        if not (qa_users or qa_matters or qa_groups):
            print("\nNothing to delete.")
            return

        # Delete in dependency order
        if qa_user_ids or qa_matter_ids:
            db.query(MatterAccess).filter(
                (MatterAccess.user_id.in_(qa_user_ids))
                | (MatterAccess.matter_id.in_(qa_matter_ids))
            ).delete(synchronize_session=False)

        if qa_matter_ids:
            try:
                from cvp.models_comments import Comment

                comment_item_ids = [
                    row.id for row in db.query(Item.id).filter(Item.matter_id.in_(qa_matter_ids))
                ]
                if comment_item_ids:
                    db.query(Comment).filter(Comment.item_id.in_(comment_item_ids)).delete(
                        synchronize_session=False
                    )
            except Exception:
                pass  # comments table may not exist in all envs

            db.query(Item).filter(Item.matter_id.in_(qa_matter_ids)).delete(
                synchronize_session=False
            )

            db.query(EvidenceFile).filter(EvidenceFile.matter_id.in_(qa_matter_ids)).delete(
                synchronize_session=False
            )

            db.query(Room).filter(Room.matter_id.in_(qa_matter_ids)).delete(
                synchronize_session=False
            )

            db.query(Matter).filter(Matter.id.in_(qa_matter_ids)).delete(synchronize_session=False)

        if qa_user_ids:
            db.query(User).filter(User.id.in_(qa_user_ids)).delete(synchronize_session=False)

        if qa_group_ids:
            db.query(Group).filter(Group.id.in_(qa_group_ids)).delete(synchronize_session=False)

        db.commit()
        print("\nCleanup complete.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR during cleanup: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
