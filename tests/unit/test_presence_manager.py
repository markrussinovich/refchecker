"""Unit tests for the realtime shared-room PresenceManager (issue #67)."""

import asyncio
import json

from backend.websocket_manager import PresenceManager


class FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket that records sent text."""

    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    def messages_of_type(self, msg_type):
        return [m for m in self.sent if m.get("type") == msg_type]


def _run(coro):
    """Run a coroutine on a fresh, isolated event loop.

    Other async suites in the same process may call ``asyncio.run`` (which
    closes its loop and resets the thread's current loop to ``None``), so we
    cannot rely on ``asyncio.get_event_loop`` returning a usable loop here.
    Create/set/close a dedicated loop per call to avoid cross-suite pollution.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_join_sends_state_to_newcomer_and_broadcasts_join():
    pm = PresenceManager()
    alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
    alice = {"user_id": 1, "name": "Alice", "email": "a@x.com"}
    bob = {"user_id": 2, "name": "Bob", "email": "b@x.com"}

    _run(pm.join(alice_ws, "batch-42", alice))
    # Alice gets her own presence_state (just herself).
    state = alice_ws.messages_of_type("presence_state")
    assert len(state) == 1
    assert [u["user_id"] for u in state[0]["users"]] == [1]
    # No one else yet → no join broadcast received by Alice.
    assert alice_ws.messages_of_type("presence_join") == []

    _run(pm.join(bob_ws, "batch-42", bob))
    # Bob receives the current roster including Alice.
    bob_state = bob_ws.messages_of_type("presence_state")[0]
    assert {u["user_id"] for u in bob_state["users"]} == {1, 2}
    # Alice is notified that Bob joined.
    join = alice_ws.messages_of_type("presence_join")
    assert len(join) == 1
    assert join[0]["user"]["user_id"] == 2
    assert {u["user_id"] for u in join[0]["users"]} == {1, 2}


def test_leave_broadcasts_when_user_fully_gone():
    pm = PresenceManager()
    alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
    _run(pm.join(alice_ws, "r", {"user_id": 1, "name": "Alice", "email": None}))
    _run(pm.join(bob_ws, "r", {"user_id": 2, "name": "Bob", "email": None}))

    _run(pm.leave(bob_ws, "r"))
    leave = alice_ws.messages_of_type("presence_leave")
    assert len(leave) == 1
    assert leave[0]["user"]["user_id"] == 2
    assert [u["user_id"] for u in leave[0]["users"]] == [1]
    assert [u["user_id"] for u in pm.roster("r")] == [1]


def test_multiple_tabs_count_once_and_no_duplicate_join_or_premature_leave():
    pm = PresenceManager()
    other_ws = FakeWebSocket()
    tab1, tab2 = FakeWebSocket(), FakeWebSocket()
    _run(pm.join(other_ws, "r", {"user_id": 9, "name": "Obs", "email": None}))

    # Same user opens two tabs.
    _run(pm.join(tab1, "r", {"user_id": 1, "name": "Ann", "email": None}))
    _run(pm.join(tab2, "r", {"user_id": 1, "name": "Ann", "email": None}))

    # Observer sees exactly one join for user 1 (second tab is deduped).
    joins = [j for j in other_ws.messages_of_type("presence_join") if j["user"]["user_id"] == 1]
    assert len(joins) == 1
    # Roster counts user 1 once.
    assert sorted(u["user_id"] for u in pm.roster("r")) == [1, 9]

    # Closing one tab must NOT broadcast a leave (user still present via tab2).
    _run(pm.leave(tab1, "r"))
    assert other_ws.messages_of_type("presence_leave") == []
    assert sorted(u["user_id"] for u in pm.roster("r")) == [1, 9]

    # Closing the last tab broadcasts the leave.
    _run(pm.leave(tab2, "r"))
    assert len(other_ws.messages_of_type("presence_leave")) == 1


def test_empty_room_cleaned_up():
    pm = PresenceManager()
    ws = FakeWebSocket()
    _run(pm.join(ws, "solo", {"user_id": 1, "name": "X", "email": None}))
    _run(pm.leave(ws, "solo"))
    assert pm.roster("solo") == []
    assert "solo" not in pm._rooms
