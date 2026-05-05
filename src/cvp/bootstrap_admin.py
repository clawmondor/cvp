"""Idempotent admin bootstrap. Called from Railway pre-deploy (release) command."""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from cvp.auth import hash_password
from cvp.config import settings
from cvp.models_auth import User


def main() -> None:
    email = os.environ.get("INITIAL_ADMIN_EMAIL")
    password = os.environ.get("INITIAL_ADMIN_PASSWORD")

    # Create a fresh engine/session so the test-monkeypatched DATABASE_URL is honoured.
    # (The module-level SessionLocal in db.py is bound at import time and would use
    # whatever URL was active when db.py was first imported.)
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with Session() as session:
        existing_admin = session.execute(
            select(User).where(User.system_role == "system_admin").limit(1)
        ).scalar_one_or_none()

        if existing_admin is not None:
            print("bootstrap-admin: skipped (existing admin present)")
            return

        if not email or not password:
            print(
                "bootstrap-admin: error — no admin exists and "
                "INITIAL_ADMIN_EMAIL / INITIAL_ADMIN_PASSWORD are not set",
                file=sys.stderr,
            )
            sys.exit(1)

        admin = User(
            email=email,
            display_name="Admin",
            password_hash=hash_password(password),
            system_role="system_admin",
            # group_id is nullable — no group required for the bootstrap admin
        )
        session.add(admin)
        session.commit()
        print(f"bootstrap-admin: created initial admin {email}")
