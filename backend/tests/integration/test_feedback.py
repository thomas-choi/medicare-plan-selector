"""WP6: feedback in both modes, the redactor on stored text, encrypted raw text only on opt-in, N9 (backend part),
the full N1 zero-write flow, and the admin API (gate, list, export of redacted fields only, triage, audit)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, delete, func, select, text

from selector import models as m
from selector.api import cookies
from tests.api_support import SENTINEL_DOCTOR, SENTINEL_DRUG, SENTINEL_ZIP, chat, client, sentinel_profile, start

pytestmark = pytest.mark.infra
GATE = "test-admin-gate-value"


@pytest.fixture
def mig(fixture_db: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(fixture_db["migrator"])
    with eng.begin() as c:
        c.execute(delete(m.feedback))
        c.execute(delete(m.feedback_counter))
    yield eng
    eng.dispose()


def snapshot(eng: Engine) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with eng.connect() as c:
        for t in sorted(m.USER_TABLES):
            n = c.execute(select(func.count()).select_from(m.metadata.tables[t])).scalar_one()
            chk = c.execute(text(f"CHECKSUM TABLE `{t}`")).all()[0][1]
            out[t] = (n, chk)
    return out


def test_n1_nosave_full_flow_writes_no_user_rows(fixture_db: dict[str, str], mig: Engine) -> None:
    before = snapshot(mig)
    c = client(fixture_db)
    start(c)
    sid_hash = cookies.decode(c.cookies.get(cookies.COOKIE)).id_hash  # type: ignore[union-attr]
    assert c.put("/api/profile", json=sentinel_profile()).status_code == 200  # intake
    cmp = c.post("/api/compare", json={}).json()  # estimate/compare (form)
    top = cmp["top"][0]["plan_key"]
    chat(c, "compare plans")  # chat turn (fake LLM)
    assert (
        c.post("/api/feedback", json={"kind": "recommendation_rating", "plan_key": top, "thumbs": 1}).json()["stored"]
        == "counter"
    )
    out = c.post(
        "/api/feedback",
        json={
            "kind": "session_outcome",
            "chosen_plan_key": top,
            "enrolled": "planned",
            "confidence": 4,
            "text": f"I take {SENTINEL_DRUG}",
        },
    ).json()
    assert out == {"stored": "counter", "linked": False, "text_dropped": True}
    assert c.post("/api/feedback", json={"kind": "general", "text": "hi"}).json()["detail"]["code"] == "use_team_form"
    c.delete("/api/session")  # end
    assert snapshot(mig) == before
    with mig.connect() as conn:
        counters = [dict(r) for r in conn.execute(select(m.feedback_counter)).mappings()]
        daily = [dict(r) for r in conn.execute(select(m.usage_daily)).mappings()]
    vals = {r["value"] for r in counters}
    assert {"up", top, "enrolled:planned", "confidence:4"} <= vals
    blob = str(counters) + str(daily)
    assert sid_hash not in blob and SENTINEL_DRUG not in blob and SENTINEL_ZIP not in blob


def test_n9_team_message_is_one_unlinked_redacted_row(fixture_db: dict[str, str], mig: Engine) -> None:
    c = client(fixture_db)
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    msg = f"The {SENTINEL_DRUG} price looks off. {SENTINEL_DOCTOR} said so. Call 602-555-1212, ZIP {SENTINEL_ZIP}."
    r = c.post("/api/feedback", json={"kind": "general", "text": msg, "to_team": True, "include_details": True})
    assert r.json() == {"stored": "message", "linked": False}
    with mig.connect() as conn:
        rows = [dict(x) for x in conn.execute(select(m.feedback)).mappings()]
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] is None and row["mode"] == "nosave" and row["text_raw_enc"] is None
    for s in (SENTINEL_DRUG, "Sentinel", "555-1212", SENTINEL_ZIP):
        assert s not in row["text_redacted"]
    c.delete("/api/session")


def test_saved_feedback_rows_linked_redacted_and_optional_raw(fixture_db: dict[str, str], mig: Engine) -> None:
    c = client(fixture_db)
    start(c, "saved")
    c.put("/api/profile", json=sentinel_profile())
    cmp = c.post("/api/compare", json={}).json()
    rid = cmp["recommendation_ids"][0]
    r = c.post(
        "/api/feedback",
        json={
            "kind": "recommendation_rating",
            "recommendation_id": rid,
            "thumbs": -1,
            "rating": 2,
            "text": f"{SENTINEL_DRUG} tier looks wrong",
        },
    )
    assert r.json()["linked"] is True
    by_key = c.post(
        "/api/feedback", json={"kind": "recommendation_rating", "plan_key": cmp["top"][1]["plan_key"], "thumbs": 1}
    )
    assert by_key.status_code == 200
    c.post(
        "/api/feedback",
        json={
            "kind": "bug",
            "text": f"Broken for {SENTINEL_DOCTOR}",
            "include_details": True,
            "context": {"page": "canvas", "view": "table", "last_tool_call_ids": ["fake_1"]},
        },
    )
    bad = c.post("/api/feedback", json={"kind": "recommendation_rating", "recommendation_id": "999999", "thumbs": 1})
    assert bad.status_code == 422
    h = cookies.decode(c.cookies.get(cookies.COOKIE))
    assert h is not None
    with mig.connect() as conn:
        rows = [dict(x) for x in conn.execute(select(m.feedback).order_by(m.feedback.c.id)).mappings()]
    assert [x["kind"] for x in rows] == ["recommendation_rating", "recommendation_rating", "bug"]
    assert all(x["session_id"] == h.id_hash for x in rows)
    assert str(rows[0]["recommendation_id"]) == rid and rows[1]["recommendation_id"] is not None
    assert SENTINEL_DRUG not in rows[0]["text_redacted"] and rows[0]["text_raw_enc"] is None
    assert rows[2]["phi_opt_in"] and rows[2]["text_raw_enc"] and b"Sentinel" not in rows[2]["text_raw_enc"]
    assert rows[2]["context_json"]["view"] == "table"
    c.delete("/api/session")  # delete-my-data: raw text gone, rows unlinked
    with mig.connect() as conn:
        rows = [dict(x) for x in conn.execute(select(m.feedback)).mappings()]
    assert all(x["session_id"] is None and x["text_raw_enc"] is None for x in rows)


def test_agent_record_feedback_tool_uses_the_same_path(fixture_db: dict[str, str], mig: Engine) -> None:
    from selector.agent.providers import Completion, ToolCall, Usage
    from selector.agent.providers.fake import FakeProvider

    script: list[Any] = [
        Completion(
            "",
            [ToolCall("t1", "record_feedback", {"plan_key": "H0028_028_0", "thumbs": 1})],
            Usage(1, 1),
            "fake",
            "fake-1",
        ),
        Completion("Thanks, noted.", [], Usage(1, 1), "fake", "fake-1"),
    ]
    c = client(fixture_db, providers=[FakeProvider(script=script)])
    start(c)
    c.put("/api/profile", json=sentinel_profile())
    chat(c, "thumbs up for H0028_028_0")
    with mig.connect() as conn:
        vals = conn.execute(select(m.feedback_counter.c.value)).scalars().all()
    assert "up" in vals
    c.delete("/api/session")


def test_admin_gate_list_export_triage_audit(fixture_db: dict[str, str], mig: Engine) -> None:
    c = client(fixture_db, admin_gate_secret=GATE)
    start(c, "saved")
    c.put("/api/profile", json=sentinel_profile())
    c.post(
        "/api/feedback",
        json={"kind": "general", "text": f"love it, my {SENTINEL_DRUG} is cheaper", "include_details": True},
    )
    assert c.get("/api/admin/feedback").status_code == 403
    assert c.get("/api/admin/feedback", headers={"X-Admin-Gate": "wrong"}).status_code == 403
    hdr = {"X-Admin-Gate": GATE, "X-Admin-User": "thomas"}
    items = c.get("/api/admin/feedback", headers=hdr).json()["items"]
    assert len(items) == 1 and "text_raw_enc" not in items[0] and SENTINEL_DRUG not in items[0]["text_redacted"]
    csv_text = c.get("/api/admin/feedback/export", headers=hdr).text
    assert csv_text.startswith("id,created_at,kind") and SENTINEL_DRUG not in csv_text
    assert "text_raw" not in csv_text
    fid = items[0]["id"]
    assert c.patch(f"/api/admin/feedback/{fid}", headers=hdr, json={"triage_status": "accepted"}).status_code == 200
    assert c.get("/api/admin/feedback", headers=hdr, params={"status": "accepted"}).json()["items"][0]["id"] == fid
    summary = c.get("/api/admin/summary", headers=hdr).json()
    assert summary["feedback_rows"]
    with mig.connect() as conn:
        actions = conn.execute(select(m.admin_audit.c.action).where(m.admin_audit.c.admin_subject == "thomas")).all()
    assert {"list_feedback", "export_feedback", "triage", "summary"} <= {a[0] for a in actions}
    off = client(fixture_db)  # blank ADMIN_GATE_SECRET → admin API off
    assert off.get("/api/admin/feedback", headers=hdr).status_code == 404
    c.delete("/api/session")


def test_gate_value_never_logged(fixture_db: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    c = client(fixture_db, admin_gate_secret=GATE)
    c.get("/api/admin/feedback", headers={"X-Admin-Gate": GATE})
    assert GATE not in caplog.text and hashlib.sha256(GATE.encode()).hexdigest() not in caplog.text
