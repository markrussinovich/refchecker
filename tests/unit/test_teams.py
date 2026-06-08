#!/usr/bin/env python3
"""DB-layer regression test for Teams (issue #66).

Exercises the create + list-my-teams + add-member paths directly against the
SQLite layer so the schema and queries stay correct. Mirrors the style of
test_seen_references_upsert.py (real on-disk SQLite, no mocks).

Note: backend.database imports aiosqlite, which is not installed in the
stdlib-only local sandbox; this test therefore runs in CI (where deps are
present). Locally the implementation is covered by py_compile.
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.database import Database  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _seed_user(db, email, name):
    """Insert a user row directly (the OAuth upsert path lives in main.py)."""
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "INSERT INTO users (provider, provider_id, email, name) VALUES (?, ?, ?, ?)",
            ("test", email, email, name),
        )
        await conn.commit()
        return cursor.lastrowid


def test_team_create_list_and_add_member():
    tmp = tempfile.mktemp(suffix='.db')

    async def run():
        db = Database(tmp)
        await db.init_db()

        owner_id = await _seed_user(db, "owner@example.com", "Owner")
        member_id = await _seed_user(db, "member@example.com", "Member")

        # Create: owner gets a team and is auto-added as a member with role 'owner'.
        team = await db.create_team("Lab Group", owner_id)
        assert team["name"] == "Lab Group"
        assert team["owner_user_id"] == owner_id
        team_id = team["id"]

        # List my teams: the owner sees exactly the one team they own.
        owner_teams = await db.get_teams_for_user(owner_id)
        assert len(owner_teams) == 1
        assert owner_teams[0]["id"] == team_id
        assert owner_teams[0]["my_role"] == "owner"
        assert owner_teams[0]["member_count"] == 1

        # A non-member sees no teams yet.
        assert await db.get_teams_for_user(member_id) == []

        # Add member by id.
        added = await db.add_team_member(team_id, member_id)
        assert added is True

        # Adding again is idempotent (no duplicate row).
        assert await db.add_team_member(team_id, member_id) is False

        members = await db.get_team_members(team_id)
        assert {m["user_id"] for m in members} == {owner_id, member_id}
        assert {m["email"] for m in members} == {"owner@example.com", "member@example.com"}

        # The new member now sees the team in their list.
        member_teams = await db.get_teams_for_user(member_id)
        assert len(member_teams) == 1
        assert member_teams[0]["id"] == team_id
        assert member_teams[0]["my_role"] == "member"
        assert member_teams[0]["member_count"] == 2

        # Add-by-email resolution helper.
        looked_up = await db.get_user_by_email("MEMBER@example.com")  # case-insensitive
        assert looked_up and looked_up["id"] == member_id

        # Membership checks.
        assert await db.is_team_member(team_id, member_id) is True
        assert await db.is_team_member(team_id, 999999) is False

    try:
        _run(run())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_team_remove_member():
    """remove_team_member deletes a membership and is reflected in counts."""
    tmp = tempfile.mktemp(suffix='.db')

    async def run():
        db = Database(tmp)
        await db.init_db()

        owner_id = await _seed_user(db, "owner@example.com", "Owner")
        member_id = await _seed_user(db, "member@example.com", "Member")

        team = await db.create_team("Lab Group", owner_id)
        team_id = team["id"]
        await db.add_team_member(team_id, member_id)
        assert await db.count_team_members(team_id) == 2

        # Removing the non-owner member works once and is then idempotent.
        assert await db.remove_team_member(team_id, member_id) is True
        assert await db.remove_team_member(team_id, member_id) is False
        assert await db.is_team_member(team_id, member_id) is False
        assert await db.count_team_members(team_id) == 1

        # The owner remains, and the removed user no longer sees the team.
        assert await db.is_team_member(team_id, owner_id) is True
        assert await db.get_teams_for_user(member_id) == []

    try:
        _run(run())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_team_leave_owner_guard_uses_member_count():
    """A sole owner can empty a team; the count > 1 guard is what the leave
    endpoint checks before allowing the owner to leave with others present."""
    tmp = tempfile.mktemp(suffix='.db')

    async def run():
        db = Database(tmp)
        await db.init_db()

        owner_id = await _seed_user(db, "owner@example.com", "Owner")
        member_id = await _seed_user(db, "member@example.com", "Member")

        team = await db.create_team("Lab Group", owner_id)
        team_id = team["id"]
        await db.add_team_member(team_id, member_id)

        # With other members present, the owner-leave guard (count > 1) holds.
        assert await db.count_team_members(team_id) > 1

        # A plain member can always leave.
        assert await db.remove_team_member(team_id, member_id) is True
        assert await db.count_team_members(team_id) == 1

        # Now the owner is alone (count == 1) and may leave to empty the team.
        assert await db.remove_team_member(team_id, owner_id) is True
        assert await db.count_team_members(team_id) == 0

    try:
        _run(run())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_presence_roster_skips_none_user_id():
    """A malformed/anonymous token (user_id=None) must not collapse the roster.

    Regression for the presence hardening: previously every None-id connection
    deduped to the same key, hiding real users. Now None entries are skipped so
    each real user is represented exactly once.
    """
    from backend.websocket_manager import PresenceManager

    members = {
        object(): {"user_id": None, "name": "Anon A"},
        object(): {"user_id": None, "name": "Anon B"},
        object(): {"user_id": 1, "name": "Alice"},
        object(): {"user_id": 1, "name": "Alice (2nd tab)"},
        object(): {"user_id": 2, "name": "Bob"},
    }
    roster = PresenceManager._roster(members)
    ids = sorted(u["user_id"] for u in roster)
    # Two real users, deduped; the None entries do not appear or collapse them.
    assert ids == [1, 2]
    assert all(u["user_id"] is not None for u in roster)


if __name__ == "__main__":
    test_team_create_list_and_add_member()
    test_team_remove_member()
    test_team_leave_owner_guard_uses_member_count()
    test_presence_roster_skips_none_user_id()
    print("ok")
