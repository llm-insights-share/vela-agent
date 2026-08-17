#!/usr/bin/env python3
"""Migrate active memory_records into Letta blocks / archival passages.

Usage (from backend/):
  python scripts/migrate_memory_to_letta.py

Idempotent: skips passages already tagged with record:<record_id>.
Requires Letta server running and letta-client installed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict

from database import SessionLocal, init_db
from models import MemoryRecord
from services.memory import letta_store


def main():
    init_db()
    db = SessionLocal()
    migrated = {"blocks": 0, "passages": 0, "skipped": 0, "errors": 0}
    try:
        if not letta_store.is_letta_enabled():
            print("Letta disabled in config; abort.")
            return
        health = letta_store.health()
        if not health.get("healthy"):
            print(f"Letta unhealthy: {health.get('error')}; abort.")
            return

        rows = (
            db.query(MemoryRecord)
            .filter(MemoryRecord.status == "active")
            .order_by(MemoryRecord.created_at.asc())
            .all()
        )
        print(f"Found {len(rows)} active memory_records")

        prefs = defaultdict(list)  # (agent_id, user_id) -> [content]
        tools = defaultdict(list)
        for r in rows:
            key = (r.agent_id, r.user_id or "")
            if r.memory_type == "provenance":
                migrated["skipped"] += 1
                continue
            if r.memory_type == "user_pref":
                prefs[key].append(r.content)
                continue
            if r.memory_type == "tool_profile":
                tools[key].append(r.content)
                continue

            # experience / task_summary -> passages
            tag_record = f"record:{r.record_id}"
            existing = letta_store.list_passages(
                db, agent_id=r.agent_id, user_id=r.user_id or "", limit=100
            )
            if any(tag_record in (p.get("tags") or []) for p in existing):
                migrated["skipped"] += 1
                continue
            tags = [r.memory_type, tag_record]
            created = letta_store.insert_passage(
                db,
                agent_id=r.agent_id,
                text=r.content,
                user_id=r.user_id or "",
                tags=tags,
            )
            if created:
                migrated["passages"] += 1
                print(f"  passage ← {r.memory_type} {r.record_id[:8]}")
            else:
                migrated["errors"] += 1

        for (agent_id, user_id), contents in prefs.items():
            value = "\n".join(f"- {c}" for c in contents if c)
            if not value:
                continue
            updated = letta_store.update_block(
                db, agent_id, "user_pref", value, user_id=user_id
            )
            if updated:
                migrated["blocks"] += 1
                print(f"  block user_pref ← {agent_id[:8]}/{user_id or 'anon'}")
            else:
                migrated["errors"] += 1

        for (agent_id, user_id), contents in tools.items():
            value = "工具调用画像（迁移）\n" + "\n".join(f"- {c}" for c in contents if c)
            updated = letta_store.update_block(
                db, agent_id, "tool_profile", value, user_id=user_id
            )
            if updated:
                migrated["blocks"] += 1
                print(f"  block tool_profile ← {agent_id[:8]}/{user_id or 'anon'}")
            else:
                migrated["errors"] += 1

        print("Done:", migrated)
    finally:
        db.close()


if __name__ == "__main__":
    main()
