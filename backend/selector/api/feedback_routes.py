"""POST /api/feedback and the admin API (DESIGN §7). Request bodies are never logged.

Admin gate: nginx does basic auth + IP allowlist for `/admin` and `/api/admin`, then sets
`X-Admin-Gate: <ADMIN_GATE_SECRET>` (and strips any client-sent value on every other location). The API compares it
in constant time; a blank `ADMIN_GATE_SECRET` turns the admin API off (404). Exports contain redacted fields only.
Every admin action is written to `admin_audit`.
"""

from __future__ import annotations

import csv
import datetime as dt
import hmac
import io
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select, update

from selector import crypto
from selector import models as m
from selector.api.routes import Session, current, st
from selector.api.state import AppState
from selector.feedback import FeedbackIn, FeedbackRejected, record
from selector.store import write_guard

router = APIRouter(prefix="/api")

EXPORT_FIELDS = (
    "id",
    "created_at",
    "kind",
    "mode",
    "linked",
    "recommendation_id",
    "rating",
    "thumbs",
    "chosen_plan_key",
    "enrolled",
    "confidence",
    "text_redacted",
    "phi_opt_in",
    "app_version",
    "prompt_version",
    "model_id",
    "triage_status",
    "triage_note",
    "context_json",
)
TRIAGE = ("new", "accepted", "test-added", "closed")


def model_id(state: AppState) -> str:
    return state.providers[0].model if state.providers else "none"


def redact_terms(sess: Session) -> list[str]:
    prof = sess.store.load_profile(sess.h)
    if prof is None:
        return []
    return [d.name for d in prof.drugs] + [p.name for p in prof.providers] + [prof.county_name or ""]


def submit(sess: Session, f: FeedbackIn) -> dict[str, Any]:
    st_ = sess.state
    try:
        key = crypto.profile_key(st_.settings)
    except crypto.CryptoError:
        key = None
    canvas = sess.store.load_canvas(sess.h)
    return record(
        st_.engine,
        mode=sess.h.mode,
        session_id_hash=sess.h.id_hash if sess.h.mode == "saved" else None,
        f=f,
        plan_year=st_.settings.plan_year,
        app_version=st_.settings.app_version,
        model_id=model_id(st_),
        redact_terms=redact_terms(sess),
        profile_key=key,
        key_version=st_.settings.profile_key_version,
        rec_ids_for_session=canvas.get("recommendation_ids") or {},
    )


@router.post("/feedback")
def feedback(body: FeedbackIn, sess: Session = Depends(current)) -> dict[str, Any]:
    try:
        return submit(sess, body)
    except FeedbackRejected as e:
        raise HTTPException(422, {"code": e.code, "message": e.message}) from e


def agent_feedback_hook(sess: Session, kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """`record_feedback` tool → the same path as the thumbs buttons."""
    return submit(
        sess, FeedbackIn(kind="recommendation_rating", plan_key=data.get("plan_key"), thumbs=data.get("thumbs"))
    )


# ------------------------------------------------------------------ admin


def admin(request: Request, state: AppState = Depends(st)) -> str:
    secret = state.settings.admin_gate_secret.get_secret_value()
    if not secret:
        raise HTTPException(404)
    got = request.headers.get("x-admin-gate", "")
    if not hmac.compare_digest(got.encode(), secret.encode()):
        raise HTTPException(403, {"code": "forbidden"})
    user = request.headers.get("x-admin-user", "") or "admin"
    return re.sub(r"[^\w@.-]", "", user)[:128] or "admin"


def audit(state: AppState, subject: str, action: str, target: str) -> None:
    with write_guard.request_mode("admin"), state.engine.begin() as c:
        c.execute(
            insert(m.admin_audit).values(
                admin_subject=subject,
                action=action,
                target=target[:255],
                created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
            )
        )


def _row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["linked"] = d.pop("session_id", None) is not None
    return {k: d.get(k) for k in EXPORT_FIELDS}


def _query(
    kind: str | None,
    status: str | None,
    since: dt.date | None,
    until: dt.date | None,
    model: str | None,
    prompt_version: str | None,
) -> Any:
    f = m.feedback.c
    cols = [c for c in m.feedback.c if c.name not in ("text_raw_enc", "key_version")]
    q = select(*cols)
    if kind:
        q = q.where(f.kind == kind)
    if status:
        q = q.where(f.triage_status == status)
    if since:
        q = q.where(f.created_at >= since)
    if until:
        q = q.where(f.created_at < until + dt.timedelta(days=1))
    if model:
        q = q.where(f.model_id == model)
    if prompt_version:
        q = q.where(f.prompt_version == prompt_version)
    return q.order_by(f.id.desc())


@router.get("/admin/feedback")
def admin_list(
    kind: str | None = Query(None, max_length=32),
    status: str | None = Query(None, max_length=16),
    since: dt.date | None = None,
    until: dt.date | None = None,
    model: str | None = Query(None, max_length=128),
    prompt_version: str | None = Query(None, max_length=32),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    subject: str = Depends(admin),
    state: AppState = Depends(st),
) -> dict[str, Any]:
    q = _query(kind, status, since, until, model, prompt_version)
    with state.engine.connect() as c:
        rows = [_row(r) for r in c.execute(q.limit(limit).offset(offset)).mappings()]
    audit(state, subject, "list_feedback", f"kind={kind or '*'} status={status or '*'}")
    return {"items": rows}


@router.get("/admin/feedback/export")
def admin_export(
    fmt: Literal["csv", "json"] = Query("csv", alias="format"),
    kind: str | None = Query(None, max_length=32),
    since: dt.date | None = None,
    until: dt.date | None = None,
    subject: str = Depends(admin),
    state: AppState = Depends(st),
) -> Response:
    with state.engine.connect() as c:
        rows = [_row(r) for r in c.execute(_query(kind, None, since, until, None, None)).mappings()]
    audit(state, subject, "export_feedback", f"format={fmt} rows={len(rows)}")
    if fmt == "json":
        import json

        return Response(json.dumps(rows, default=str), media_type="application/json")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return Response(
        buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="feedback.csv"'}
    )


class TriageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    triage_status: Literal["new", "accepted", "test-added", "closed"]
    triage_note: str | None = Field(default=None, max_length=512)


@router.patch("/admin/feedback/{fid}")
def admin_triage(
    fid: int, body: TriageIn, subject: str = Depends(admin), state: AppState = Depends(st)
) -> dict[str, Any]:
    with write_guard.request_mode("admin"), state.engine.begin() as c:
        n = c.execute(
            update(m.feedback)
            .where(m.feedback.c.id == fid)
            .values(triage_status=body.triage_status, triage_note=body.triage_note)
        ).rowcount
    if not n:
        raise HTTPException(404)
    audit(state, subject, "triage", f"feedback:{fid} -> {body.triage_status}")
    return {"ok": True}


@router.get("/admin/summary")
def admin_summary(
    days: int = Query(30, ge=1, le=366), subject: str = Depends(admin), state: AppState = Depends(st)
) -> dict[str, Any]:
    since = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days)
    fc = m.feedback_counter.c
    with state.engine.connect() as c:
        counters = c.execute(
            select(fc.kind, fc.value, func.sum(fc.count)).where(fc.day >= since).group_by(fc.kind, fc.value)
        ).all()
        by_kind = c.execute(
            select(m.feedback.c.kind, m.feedback.c.triage_status, func.count())
            .where(m.feedback.c.created_at >= since)
            .group_by(m.feedback.c.kind, m.feedback.c.triage_status)
        ).all()
        usage = c.execute(
            select(
                m.usage_daily.c.mode,
                func.sum(m.usage_daily.c.cost_micro_usd),
                func.sum(m.usage_daily.c.tokens_in + m.usage_daily.c.tokens_out),
            )
            .where(m.usage_daily.c.day >= since)
            .group_by(m.usage_daily.c.mode)
        ).all()
    ratings = {v: int(n) for k, v, n in counters if k == "recommendation_rating"}
    up, down = ratings.get("up", 0), ratings.get("down", 0)
    audit(state, subject, "summary", f"days={days}")
    return {
        "since": since.isoformat(),
        "thumbs": {"up": up, "down": down, "up_rate": round(up / (up + down), 3) if up + down else None},
        "stars": {v: n for v, n in ratings.items() if v.startswith("stars:")},
        "outcomes": {v: int(n) for k, v, n in counters if k == "session_outcome"},
        "feedback_rows": [{"kind": k, "status": s, "count": int(n)} for k, s, n in by_kind],
        "llm_usage": [{"mode": md, "cost_usd": int(cst or 0) / 1e6, "tokens": int(t or 0)} for md, cst, t in usage],
    }
