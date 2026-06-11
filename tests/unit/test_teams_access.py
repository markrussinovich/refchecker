#!/usr/bin/env python3
"""Team-scoped shared-check access tests (R26).

Covers the new DB + endpoint behaviour for sharing a batch / single check with
a team so members can read it:

  - a team member opening a shared batch gets 200 (summary + checks),
  - a non-member gets 404 (the same opaque response an unknown batch returns),
  - the presence room access gate accepts members and rejects non-members,
  - sharing a single check with a team it can read, and listing team checks.

Mirrors test_api_authorization.py's harness (REFCHECKER_MULTIUSER=true, the
module reloaded against a temp DB, handlers invoked directly). Like the other
backend tests this needs aiosqlite, so it runs in CI; locally it is covered by
py_compile.
"""

import asyncio
import importlib
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.database import Database  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


async def _create_user(api_main, db, provider_id):
    user_id = await db.create_or_update_user(
        provider="github",
        provider_id=provider_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
    )
    return api_main.UserInfo(
        id=user_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
        provider="github",
        is_admin=False,
    )


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_teams_access")
    monkeypatch.setenv("REFCHECKER_MULTIUSER", "true")
    api_main = importlib.import_module("backend.main")
    api_main = importlib.reload(api_main)
    temp_db = Database(str(tmp_path / "teams_access.db"))
    _run(temp_db.init_db())
    api_main.active_checks.clear()
    monkeypatch.setattr(api_main, "db", temp_db)
    yield api_main, temp_db
    api_main.active_checks.clear()


async def _seed_shared_batch(db, owner, member_user_id=None):
    """Create a 2-paper batch owned by ``owner`` and share it with a fresh team
    that ``member_user_id`` (if given) belongs to. Returns (batch_id, team_id)."""
    batch_id = "batch-shared-1"
    for title, src in (
        ("Batch one", "https://arxiv.org/abs/1706.03762"),
        ("Batch two", "https://arxiv.org/abs/1810.04805"),
    ):
        await db.create_pending_check(
            paper_title=title,
            paper_source=src,
            source_type="url",
            batch_id=batch_id,
            batch_label="Owner batch",
            user_id=owner.id,
        )
    team = await db.create_team("Lab Group", owner.id)
    team_id = team["id"]
    if member_user_id is not None:
        await db.add_team_member(team_id, member_user_id)
    # Share the whole batch with the team.
    await db.set_batch_team(batch_id, team_id, user_id=owner.id)
    return batch_id, team_id


def test_team_member_opens_shared_batch_200_nonmember_404(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-share"))
    member = _run(_create_user(api_main, db, "member-share"))
    stranger = _run(_create_user(api_main, db, "stranger-share"))

    batch_id, team_id = _run(_seed_shared_batch(db, owner, member_user_id=member.id))

    # The team member can open the shared batch — summary + both checks.
    member_view = _run(api_main.get_batch(batch_id, member))
    assert member_view["batch_id"] == batch_id
    assert len(member_view["checks"]) == 2

    # The owner of course still sees it.
    owner_view = _run(api_main.get_batch(batch_id, owner))
    assert len(owner_view["checks"]) == 2

    # A non-member gets the opaque 404 (sharing is not enumerable).
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_batch(batch_id, stranger))
    assert exc.value.status_code == 404


def test_nonmember_cannot_mutate_shared_batch(auth_db):
    """Team membership grants READ access only — a member can't cancel/delete
    another owner's batch, and a stranger gets 404 on the mutating routes."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-mut"))
    member = _run(_create_user(api_main, db, "member-mut"))

    batch_id, team_id = _run(_seed_shared_batch(db, owner, member_user_id=member.id))

    # A member may read but not cancel/delete (those stay owner-scoped).
    with pytest.raises(HTTPException) as exc:
        _run(api_main.cancel_batch(batch_id, member))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _run(api_main.delete_batch(batch_id, member))
    assert exc.value.status_code == 404


def test_presence_room_access_gate(auth_db):
    """The presence room gate accepts a member and rejects a non-member for a
    batch room, and lets non-batch rooms through."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-presence"))
    member = _run(_create_user(api_main, db, "member-presence"))
    stranger = _run(_create_user(api_main, db, "stranger-presence"))

    batch_id, team_id = _run(_seed_shared_batch(db, owner, member_user_id=member.id))
    room = f"batch-{batch_id}"

    assert _run(api_main._can_access_presence_room(room, owner.id)) is True
    assert _run(api_main._can_access_presence_room(room, member.id)) is True
    assert _run(api_main._can_access_presence_room(room, stranger.id)) is False
    # A non-batch room keeps the prior authenticated-only behaviour.
    assert _run(api_main._can_access_presence_room("some-check-99", stranger.id)) is True


def test_share_single_check_with_team_and_list(auth_db):
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-single"))
    member = _run(_create_user(api_main, db, "member-single"))
    stranger = _run(_create_user(api_main, db, "stranger-single"))

    team = _run(db.create_team("Lab", owner.id))
    team_id = team["id"]
    _run(db.add_team_member(team_id, member.id))

    check_id = _run(db.create_pending_check(
        paper_title="Owner solo check",
        paper_source="https://arxiv.org/abs/2005.14165",
        source_type="url",
        user_id=owner.id,
    ))

    # Owner shares the single check with the team.
    resp = _run(api_main.share_check_with_team(
        check_id, api_main.CheckShareRequest(team_id=team_id), owner))
    assert resp["shared"] is True and resp["team_id"] == team_id

    # Members (and owner) can list the team's shared checks; the check is there.
    member_checks = _run(api_main.list_team_checks(team_id, member))["checks"]
    assert any(c["id"] == check_id for c in member_checks)

    # A non-member gets 404 listing the team's checks.
    with pytest.raises(HTTPException) as exc:
        _run(api_main.list_team_checks(team_id, stranger))
    assert exc.value.status_code == 404

    # Sharing with a team you don't belong to is rejected.
    other_team = _run(db.create_team("Other", stranger.id))
    with pytest.raises(HTTPException) as exc:
        _run(api_main.share_check_with_team(
            check_id, api_main.CheckShareRequest(team_id=other_team["id"]), owner))
    assert exc.value.status_code == 403

    # Unshare (team_id 0/None) clears the share.
    resp = _run(api_main.share_check_with_team(
        check_id, api_main.CheckShareRequest(team_id=0), owner))
    assert resp["shared"] is False
    assert _run(db.get_team_checks(team_id)) == []


def test_team_member_opens_shared_single_check_200_nonmember_404(auth_db):
    """R26 regression: a check shared with a team via ``share_check_with_team``
    is openable through ``get_check_detail`` by a member (200) but not a
    non-member (404). This is the path TeamMenu's "Shared checks" list hits
    (selectCheck -> getCheckDetail); without team-aware read it 404'd."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-detail"))
    member = _run(_create_user(api_main, db, "member-detail"))
    stranger = _run(_create_user(api_main, db, "stranger-detail"))

    team = _run(db.create_team("Detail team", owner.id))
    team_id = team["id"]
    _run(db.add_team_member(team_id, member.id))

    check_id = _run(db.create_pending_check(
        paper_title="Shared solo check",
        paper_source="https://arxiv.org/abs/2005.14165",
        source_type="url",
        user_id=owner.id,
    ))

    # Before sharing, a member can NOT open it (it's owner-private).
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_check_detail(check_id, member))
    assert exc.value.status_code == 404

    # Owner shares the single check with the team.
    _run(api_main.share_check_with_team(
        check_id, api_main.CheckShareRequest(team_id=team_id), owner))

    # The owner still opens it; the member can now open it (no 404).
    assert _run(api_main.get_check_detail(check_id, owner))["id"] == check_id
    member_view = _run(api_main.get_check_detail(check_id, member))
    assert member_view["id"] == check_id

    # A non-member still gets the opaque 404 (sharing is not enumerable).
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_check_detail(check_id, stranger))
    assert exc.value.status_code == 404

    # Unsharing revokes the member's read access again.
    _run(api_main.share_check_with_team(
        check_id, api_main.CheckShareRequest(team_id=0), owner))
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_check_detail(check_id, member))
    assert exc.value.status_code == 404


def test_team_member_exports_and_scores_shared_check(auth_db):
    """R26 regression: sibling read endpoints on the shared-check detail view
    (export + health) are also team-aware, so the member's view has no dead
    buttons. A non-member still gets 404."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-export"))
    member = _run(_create_user(api_main, db, "member-export"))
    stranger = _run(_create_user(api_main, db, "stranger-export"))

    team = _run(db.create_team("Export team", owner.id))
    team_id = team["id"]
    _run(db.add_team_member(team_id, member.id))

    check_id = _run(db.create_pending_check(
        paper_title="Shared scored check",
        paper_source="https://arxiv.org/abs/2005.14165",
        source_type="url",
        user_id=owner.id,
    ))
    _run(api_main.share_check_with_team(
        check_id, api_main.CheckShareRequest(team_id=team_id), owner))

    # Member can pull the health score and the HTML export of the shared check.
    health = _run(api_main.get_check_health(check_id, member))
    assert health["check_id"] == check_id
    export_resp = _run(api_main.export_check_html(check_id, True, member))
    assert export_resp.status_code == 200

    # A non-member gets 404 on both.
    with pytest.raises(HTTPException) as exc:
        _run(api_main.get_check_health(check_id, stranger))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _run(api_main.export_check_html(check_id, True, stranger))
    assert exc.value.status_code == 404


def test_db_get_check_by_id_team_scoped(auth_db):
    """Direct DB-layer coverage: ``get_check_by_id`` honours ``team_ids`` —
    a team-shared check is visible to a member, owner-private otherwise."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-dbcheck"))
    member = _run(_create_user(api_main, db, "member-dbcheck"))

    team = _run(db.create_team("DB check team", owner.id))
    team_id = team["id"]
    _run(db.add_team_member(team_id, member.id))

    check_id = _run(db.create_pending_check(
        paper_title="row", paper_source="x", source_type="url", user_id=owner.id,
    ))
    member_team_ids = _run(db.get_user_team_ids(member.id))

    # Owner-scoped read with the member's id + teams: not shared yet -> None.
    assert _run(db.get_check_by_id(check_id, user_id=member.id, team_ids=member_team_ids)) is None

    _run(db.set_check_team(check_id, team_id))
    # Now visible to the member via the team clause...
    got = _run(db.get_check_by_id(check_id, user_id=member.id, team_ids=member_team_ids))
    assert got is not None and got["id"] == check_id
    # ...but a member with no matching team_ids still can't see it.
    assert _run(db.get_check_by_id(check_id, user_id=member.id, team_ids=[])) is None
    # The owner sees it regardless.
    assert _run(db.get_check_by_id(check_id, user_id=owner.id))["id"] == check_id


def test_db_get_user_team_ids_and_set_check_team(auth_db):
    """Direct DB-layer coverage for the new helpers (R26)."""
    api_main, db = auth_db
    owner = _run(_create_user(api_main, db, "owner-db"))
    member = _run(_create_user(api_main, db, "member-db"))

    team = _run(db.create_team("DB team", owner.id))
    team_id = team["id"]
    _run(db.add_team_member(team_id, member.id))

    assert team_id in _run(db.get_user_team_ids(member.id))
    assert _run(db.get_user_team_ids(member.id + 9999)) == []

    check_id = _run(db.create_pending_check(
        paper_title="row", paper_source="x", source_type="url", user_id=owner.id,
    ))
    assert _run(db.set_check_team(check_id, team_id)) is True
    info = _run(db.get_check_batch_team(check_id))
    assert info["team_id"] == team_id


if __name__ == "__main__":
    print("Run with pytest (requires aiosqlite).")
