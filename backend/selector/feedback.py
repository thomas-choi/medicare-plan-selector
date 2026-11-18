"""Feedback (DESIGN §7, §8.5 Feedback).

Saved mode: rows in `feedback`, linked to the session; free text goes through the redactor into `text_redacted`;
the raw text is stored (AES-GCM, `PROFILE_ENC_KEY`) only when the user ticks "Include my details".

No-save mode: ratings and outcomes only increment `feedback_counter` (no session, no plan link for ratings, no
text). The separate "Send a message to the team" form (`to_team: true`, the UI shows the storage notice first)
stores one redacted row with `session_id = NULL` and `mode = 'nosave'`; raw text is never kept for No-save.

Both modes also count ratings/outcomes in `feedback_counter`, so the admin aggregates cover everyone.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, insert, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from selector import crypto
from selector import models as m
from selector.agent.prompts import PROMPT_VERSION
from selector.redact import redact
from selector.store import write_guard

PLAN_KEY = r"^[HRSE]\d{4}_\d{3}_\d{1,3}$"
TEXT_KINDS = ("general", "bug")


class BugContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str = Field(default="", max_length=64, pattern=r"^[\w/ .:-]*$")
    view: str = Field(default="", max_length=64, pattern=r"^[\w/ .:-]*$")
    last_tool_call_ids: list[str] = Field(default_factory=list, max_length=10)


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["recommendation_rating", "session_outcome", "general", "bug"]
    recommendation_id: str | None = Field(default=None, max_length=32)
    plan_key: str | None = Field(default=None, pattern=PLAN_KEY)
    thumbs: Literal[1, -1] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    chosen_plan_key: str | None = Field(default=None, pattern=r"^([HRSE]\d{4}_\d{3}_\d{1,3}|other|undecided)$")
    enrolled: Literal["yes", "no", "planned"] | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, max_length=2000)
    include_details: bool = False
    to_team: bool = False
    context: BugContext | None = None

    @model_validator(mode="after")
    def _shape(self) -> FeedbackIn:
        if self.kind == "recommendation_rating" and self.thumbs is None and self.rating is None:
            raise ValueError("a rating needs thumbs or stars")
        if self.kind == "session_outcome" and self.chosen_plan_key is None:
            raise ValueError("pick a plan, other or undecided")
        if self.kind in TEXT_KINDS and not (self.text and self.text.strip()):
            raise ValueError("please write a message")
        return self


class FeedbackRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def bump_counters(conn: Connection, plan_year: int, kind: str, values: list[str], model_id: str) -> None:
    day = dt.datetime.now(dt.UTC).date()
    for v in values:
        stmt = mysql_insert(m.feedback_counter).values(
            day=day,
            plan_year=plan_year,
            kind=kind,
            value=v[:32],
            prompt_version=PROMPT_VERSION,
            model_id=model_id[:128],
            count=1,
        )
        conn.execute(stmt.on_duplicate_key_update(count=m.feedback_counter.c.count + 1))


def counter_values(f: FeedbackIn) -> list[str]:
    vals: list[str] = []
    if f.kind == "recommendation_rating":
        if f.thumbs is not None:
            vals.append("up" if f.thumbs == 1 else "down")
        if f.rating is not None:
            vals.append(f"stars:{f.rating}")
    elif f.kind == "session_outcome":
        vals.append(f.chosen_plan_key or "undecided")
        if f.enrolled:
            vals.append(f"enrolled:{f.enrolled}")
        if f.confidence:
            vals.append(f"confidence:{f.confidence}")
    return vals


def record(
    engine: Engine,
    *,
    mode: str,
    session_id_hash: str | None,
    f: FeedbackIn,
    plan_year: int,
    app_version: str,
    model_id: str,
    redact_terms: list[str],
    profile_key: bytes | None,
    key_version: int,
    rec_ids_for_session: dict[str, str] | None = None,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)
    counters = counter_values(f)
    if mode == "nosave":
        if f.kind in TEXT_KINDS:
            if not f.to_team:
                raise FeedbackRejected(
                    "use_team_form", "In No-save mode, messages go through 'Send a message to the team'."
                )
            with write_guard.allow_writes("feedback"), engine.begin() as c:
                c.execute(
                    insert(m.feedback).values(
                        session_id=None,
                        kind=f.kind,
                        text_redacted=redact(f.text or "", redact_terms),
                        text_raw_enc=None,
                        key_version=None,
                        phi_opt_in=False,
                        mode="nosave",
                        app_version=app_version,
                        prompt_version=PROMPT_VERSION,
                        model_id=model_id,
                        created_at=now,
                        triage_status="new",
                        rating=f.rating,
                        context_json=_context(f),
                    )
                )
            return {"stored": "message", "linked": False}
        with engine.begin() as c:
            bump_counters(c, plan_year, f.kind, counters, model_id)
        return {"stored": "counter", "linked": False, "text_dropped": bool(f.text)}

    # Saved mode
    rec_id: int | None = None
    if f.kind == "recommendation_rating":
        rid = f.recommendation_id or (rec_ids_for_session or {}).get(f.plan_key or "")
        if rid is not None:
            if not rid.isdigit():
                raise FeedbackRejected("unknown_recommendation", "That recommendation isn't in your session.")
            with engine.connect() as c:
                ok = c.execute(
                    select(m.recommendation.c.id).where(
                        m.recommendation.c.id == int(rid), m.recommendation.c.session_id == session_id_hash
                    )
                ).first()
            if ok is None:
                raise FeedbackRejected("unknown_recommendation", "That recommendation isn't in your session.")
            rec_id = int(rid)
    text = (f.text or "").strip()
    raw_enc = None
    if text and f.include_details and profile_key is not None:
        raw_enc = crypto.encrypt(profile_key, text.encode(), b"feedback")
    values: dict[str, Any] = {
        "session_id": session_id_hash,
        "kind": f.kind,
        "recommendation_id": rec_id,
        "rating": f.rating,
        "thumbs": f.thumbs,
        "chosen_plan_key": f.chosen_plan_key if f.kind == "session_outcome" else None,
        "enrolled": {"yes": True, "no": False}.get(f.enrolled or ""),
        "confidence": f.confidence,
        "text_redacted": redact(text, redact_terms) if text else None,
        "text_raw_enc": raw_enc,
        "key_version": key_version if raw_enc else None,
        "phi_opt_in": raw_enc is not None,
        "mode": "saved",
        "app_version": app_version,
        "prompt_version": PROMPT_VERSION,
        "model_id": model_id,
        "created_at": now,
        "triage_status": "new",
        "context_json": _context(f),
    }
    with engine.begin() as c:
        res = c.execute(insert(m.feedback).values(**values))
        bump_counters(c, plan_year, f.kind, counters, model_id)
    pk = res.inserted_primary_key
    return {"stored": "row", "linked": True, "id": str(pk[0]) if pk else None}


def _context(f: FeedbackIn) -> dict[str, Any] | None:
    ctx: dict[str, Any] = {}
    if f.context is not None:
        ctx.update(f.context.model_dump())
    if f.enrolled == "planned":
        ctx["enrolled"] = "planned"
    return ctx or None
