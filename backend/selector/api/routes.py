"""Session, profile, lookup and chat endpoints (DESIGN §6, §8.1, §8.5).

Request and response bodies of /api/chat, /api/profile and /api/feedback are never logged (see `logging_mw`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi import Path as Path_
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from selector import glossary
from selector.agent import tools as T
from selector.agent.orchestrator import BudgetExceeded, Orchestrator, TurnResult
from selector.agent.policy import ESTIMATE_DISCLAIMER
from selector.agent.providers import ProviderError, ToolCall
from selector.agent.providers.factory import provider_label
from selector.api import cookies
from selector.api.state import AppState, SavedModeUnavailable
from selector.geo.resolve import counties_in_state, resolve_zip
from selector.lookups import LookupError_
from selector.profile import Profile
from selector.quotas import QuotaExceeded
from selector.store import write_guard
from selector.store.base import CONSENT_VERSION, SessionExpired, SessionHandle, SessionMeta, StoredMessage, now_utc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

DISCLAIMER = (
    "Estimates only. This tool is not affiliated with Medicare or any plan and does not enroll you. "
    "Confirm costs, drugs and doctors on Medicare.gov Plan Finder or with the plan before you enroll."
)


def client_ip(request: Request) -> str | None:
    """uvicorn runs with --proxy-headers behind nginx, so this is the real client address. Never logged."""
    return request.client.host if request.client else None


def st(request: Request) -> AppState:
    s: AppState = request.app.state.msp
    return s


class Session:
    """A request's live session: handle, store and metadata."""

    def __init__(self, state: AppState, h: SessionHandle, meta: SessionMeta) -> None:
        self.state = state
        self.h = h
        self.meta = meta
        self.store = state.store(h)


def current(request: Request, state: AppState = Depends(st)) -> Session:
    h = cookies.from_request(request)
    if h is None:
        raise HTTPException(401, {"code": "no_session", "message": "Start a session first."})
    try:
        meta = state.store(h).get_meta(h)
    except SavedModeUnavailable as e:
        raise HTTPException(401, {"code": "no_session", "message": "Saved mode is off."}) from e
    if meta is None:
        raise HTTPException(401, {"code": "session_expired", "message": "Your session ended. Start a new one."})
    return Session(state, h, meta)


# ------------------------------------------------------------------ config


@router.get("/config")
def config(state: AppState = Depends(st)) -> dict[str, Any]:
    s = state.settings
    return {
        "plan_year": s.plan_year,
        "default_mode": s.default_session_mode,
        "modes": ["nosave", "saved"] if state.saved else ["nosave"],
        "consent_version": CONSENT_VERSION,
        "retention_days": s.retention_days,
        "feedback_retention_days": s.feedback_retention_days,
        "ephemeral_idle_minutes": s.ephemeral_idle_minutes,
        "ephemeral_max_hours": s.ephemeral_max_hours,
        "llm_enabled": state.llm_enabled and not state.llm_paused(),
        "llm_provider_label": provider_label(s) if state.llm_enabled else None,
        "captcha_provider": s.captcha_provider,
        "limits": {"message_chars": s.max_message_chars, "drugs": s.max_drugs, "providers": s.max_providers},
        "disclaimer": DISCLAIMER,
        "estimate_disclaimer": ESTIMATE_DISCLAIMER,
        "checklist": T.CHECKLIST,
        "glossary": glossary.as_list(),
        "allowed_link_hosts": ["medicare.gov", "cms.gov", "shiphelp.org"],
        "app_version": s.app_version,
    }


# ------------------------------------------------------------------ session


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["nosave", "saved"]
    consent_version: str = Field(max_length=16)
    accept_terms: bool
    consent_feedback_phi: bool = False


def _session_view(sess: Session, *, full: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "session": {"mode": sess.meta.mode, "expires_at": sess.meta.expires_at, "plan_year": sess.meta.plan_year}
    }
    if full:
        prof = sess.store.load_profile(sess.h)
        out["profile"] = prof.model_dump(mode="json") if prof else None
        out["chat"] = [
            {"role": m.role, "content": m.content, "citations": m.citations} for m in sess.store.load_chat(sess.h)
        ]
        out["canvas"] = sess.store.load_canvas(sess.h)
    return out


def _create(state: AppState, mode: str, consent_phi: bool, request: Request) -> tuple[SessionHandle, SessionMeta]:
    h = cookies.new_handle(mode)
    now = now_utc().isoformat()
    meta = SessionMeta(mode, now, now, CONSENT_VERSION, state.settings.plan_year, mode == "saved", consent_phi)
    ip_hash = None
    if state.quotas is not None:
        try:
            ip_hash = state.quotas.on_new_session(client_ip(request))
        except QuotaExceeded as e:
            raise HTTPException(429, {"code": e.code, "message": e.message}) from e
    with write_guard.request_mode(mode):
        state.store(h).create(h, meta, ip_hash if mode == "saved" else None)
    return h, meta


@router.post("/session")
def create_session(body: SessionIn, request: Request, state: AppState = Depends(st)) -> JSONResponse:
    if not body.accept_terms:
        raise HTTPException(400, {"code": "consent_required", "message": "Please accept the terms to continue."})
    if body.mode == "saved" and state.saved is None:
        raise HTTPException(400, {"code": "saved_unavailable", "message": "Saved mode isn't available right now."})
    # Switching modes starts a new session: end the old No-save one now (a Saved one stays until deleted).
    old = cookies.from_request(request)
    if old is not None and old.mode == "nosave":
        state.ephemeral.delete(old)
    h, meta = _create(state, body.mode, body.consent_feedback_phi and body.mode == "saved", request)
    resp = JSONResponse({"session": {"mode": meta.mode, "expires_at": meta.expires_at, "plan_year": meta.plan_year}})
    cookies.set_cookie(resp, h, state.settings)
    return resp


@router.get("/session")
def get_session(request: Request, state: AppState = Depends(st)) -> JSONResponse:
    h = cookies.from_request(request)
    if h is None:
        return JSONResponse({"session": None})
    try:
        meta = state.store(h).get_meta(h)
    except SavedModeUnavailable:
        meta = None
    if meta is None:
        if h.mode == "nosave":
            # An old No-save cookie (expired, or the API restarted): nothing of it is left, so the user simply gets
            # a fresh, empty No-save session under the consent they already gave (N5).
            nh, nmeta = _create(state, "nosave", False, request)
            resp = JSONResponse(
                {
                    "session": {"mode": "nosave", "expires_at": nmeta.expires_at, "plan_year": nmeta.plan_year},
                    "renewed": True,
                    "profile": None,
                    "chat": [],
                    "canvas": {},
                }
            )
            cookies.set_cookie(resp, nh, state.settings)
            return resp
        resp = JSONResponse({"session": None, "expired": True})
        cookies.clear_cookie(resp, state.settings)
        return resp
    try:
        return JSONResponse(_session_view(Session(state, h, meta), full=True))
    except SessionExpired:
        resp = JSONResponse({"session": None, "expired": True})
        cookies.clear_cookie(resp, state.settings)
        return resp


@router.delete("/session")
def delete_session(request: Request, state: AppState = Depends(st)) -> JSONResponse:
    """ "End session & erase" (No-save) and "Delete my data" (Saved). Always clears the cookie."""
    h = cookies.from_request(request)
    deleted = 0
    if h is not None:
        try:
            store = state.store(h)
        except SavedModeUnavailable:
            store = None
        if store is not None:
            with write_guard.request_mode(h.mode):
                deleted = store.delete(h)
    resp = JSONResponse({"deleted": True, "items": deleted})
    cookies.clear_cookie(resp, state.settings)
    return resp


@router.post("/session/end", status_code=204)
def end_session(request: Request, state: AppState = Depends(st)) -> Response:
    """`navigator.sendBeacon` on pagehide (wipe trigger 4): No-save data expires after a short grace period, so a
    reload (which also fires pagehide) doesn't lose the session. Saved sessions are unaffected."""
    h = cookies.from_request(request)
    if h is not None and h.mode == "nosave":
        state.ephemeral.end_soon(h, state.settings.ephemeral_end_grace_seconds)
    return Response(status_code=204)


# ------------------------------------------------------------------ profile + lookups


@router.put("/profile")
def put_profile(profile: Profile, sess: Session = Depends(current)) -> dict[str, Any]:
    s = sess.state.settings
    if len(profile.drugs) > s.max_drugs or len(profile.providers) > s.max_providers:
        raise HTTPException(422, {"code": "too_many", "message": "Too many drugs or doctors."})
    sess.store.save_profile(sess.h, profile)
    return {"profile": profile.model_dump(mode="json")}


@router.get("/location")
def location(zip: str = Query(pattern=r"^\d{5}$"), sess: Session = Depends(current)) -> dict[str, Any]:
    with sess.state.engine.begin() as c:
        res = resolve_zip(c, zip, hud=sess.state.hud, may_write_cache=sess.h.mode == "saved")
    return {"zip": res.zip, "counties": [o.as_dict() for o in res.counties], "source": res.source, "note": res.note}


@router.get("/counties")
def counties(
    state_code: str = Query(alias="state", pattern=r"^[A-Za-z]{2}$"), sess: Session = Depends(current)
) -> dict[str, Any]:
    with sess.state.engine.connect() as c:
        return {"counties": [o.as_dict() for o in counties_in_state(c, state_code)]}


@router.get("/drugs")
def drugs(q: str = Query(min_length=2, max_length=80), sess: Session = Depends(current)) -> dict[str, Any]:
    if sess.state.rxnav is None:
        raise HTTPException(503, {"code": "lookup_unavailable", "message": "Drug search is off."})
    try:
        res = sess.state.rxnav.find(q)
    except LookupError_ as e:
        raise HTTPException(503, {"code": "lookup_failed", "message": "Drug search is unavailable."}) from e
    # `matched_as`/`how` tell the UI what was actually found, so an empty or fallback result is never silent.
    return {"candidates": [d.__dict__ for d in res.candidates], "matched_as": res.matched_as, "how": res.how}


@router.get("/providers")
def providers(
    last_name: str = Query(min_length=2, max_length=60),
    first_name: str = Query("", max_length=60),
    state_code: str = Query("", alias="state", pattern=r"^([A-Za-z]{2})?$"),
    sess: Session = Depends(current),
) -> dict[str, Any]:
    if sess.state.nppes is None:
        raise HTTPException(503, {"code": "lookup_unavailable", "message": "Doctor search is off."})
    try:
        cands = sess.state.nppes.search(last_name, first_name, state_code.upper())
    except LookupError_ as e:
        raise HTTPException(503, {"code": "lookup_failed", "message": "Doctor search is unavailable."}) from e
    return {
        "candidates": [c.__dict__ for c in cands],
        "note": "Pick your doctor to check each plan's public directory. Listings can be out of date: call the plan.",
    }


class NetworkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    npis: list[str] = Field(min_length=1, max_length=15)
    plan_keys: list[str] = Field(min_length=1, max_length=60)


@router.post("/providers/network")
def providers_network(body: NetworkIn, sess: Session = Depends(current)) -> dict[str, Any]:
    """Directory listing status of NPIs for plans in the session's county (addendum A3, A6). Only the NPIs leave
    the server; nothing is stored."""
    try:
        args = T.CheckProviderNetworkArgs(npis=body.npis, plan_keys=body.plan_keys)
    except ValueError as e:
        raise HTTPException(422, {"code": "invalid", "message": "Check the NPIs and plan IDs."}) from e
    profile = sess.store.load_profile(sess.h) or Profile()
    ctx = tool_context(sess, profile, {})
    try:
        out = T.provider_network(ctx, args.npis, args.plan_keys)
    except T.ToolFailure as e:
        status = 503 if e.code == "lookup_unavailable" else 422
        raise HTTPException(status, {"code": e.code, "message": e.user_message}) from e
    out.pop("src_ref", None)
    return out


# ------------------------------------------------------------------ plan benefits (addendum A4)


@router.get("/plans/{plan_key}/benefits")
def plan_benefits(
    plan_key: str = Path_(pattern=r"^[HRSE]\d{4}_\d{3}_\d{1,3}$"),
    category: Literal["dental"] = "dental",
    sess: Session = Depends(current),
) -> dict[str, Any]:
    """Dental benefits of one plan from CMS PBP b16 (public plan data; nothing about the user is read)."""
    ctx = T.ToolContext(sess.state.engine, sess.state.settings, Profile())
    try:
        out = T.plan_benefits(ctx, plan_key, category)
    except T.ToolFailure as e:
        raise HTTPException(404, {"code": "unknown_plan", "message": e.user_message}) from e
    return out


# ------------------------------------------------------------------ chat (SSE)


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


def _chunks(text: str, size: int = 160) -> Iterator[str]:
    """The orchestrator validates a whole answer before anyone sees it (DESIGN §8.3), so we stream the validated
    text in chunks rather than raw model tokens."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def tool_context(sess: Session, profile: Profile, canvas: dict[str, Any]) -> T.ToolContext:
    st_ = sess.state
    hook = st_.extras.get("feedback_hook")
    return T.ToolContext(
        engine=st_.engine,
        settings=st_.settings,
        profile=profile,
        canvas=canvas,
        mode=sess.h.mode,
        hud=st_.hud,
        rxnav=st_.rxnav,
        nppes=st_.nppes,
        directory=st_.directory,
        feedback_hook=(lambda kind, d: hook(sess, kind, d)) if hook else None,
    )


def persist_turn(sess: Session, user_text: str, res: TurnResult, profile: Profile) -> list[str]:
    st_ = sess.state
    store = sess.store
    if res.profile_changed:
        store.save_profile(sess.h, profile)
    store.save_canvas(sess.h, res.canvas)
    tin = sum(u.tokens_in for _, _, u in res.usage)
    tout = sum(u.tokens_out for _, _, u in res.usage)
    now = now_utc().isoformat()
    store.append_chat(
        sess.h,
        [
            StoredMessage("user", user_text[: st_.settings.max_message_chars], now),
            StoredMessage("assistant", res.text, now, res.model_id, res.citations),
        ],
        (tin, tout),
    )
    if any(c["name"] == "compare_plans" for c in res.tool_calls):
        return save_top(sess, T.ToolContext(st_.engine, st_.settings, profile, res.canvas), profile)
    return []


def save_top(sess: Session, ctx: T.ToolContext, profile: Profile) -> list[str]:
    """Record the top plans shown (Saved: `recommendation` rows, the anchor for linked ratings; No-save: Redis)."""
    st_ = sess.state
    rec_ids: list[str] = []
    if ctx.canvas.get("rows"):
        top = [r for r in ctx.canvas["rows"] if r.get("rank")][:5]
        w = profile.weights.model_dump()
        rec_ids = sess.store.save_recommendations(
            sess.h, [{**r, "weights": w, "plan_year": st_.settings.plan_year} for r in top], ctx.data_vintage()
        )
        # The cards' feedback widgets refer to these ids.
        ctx.canvas["recommendation_ids"] = dict(zip([r["plan_key"] for r in top], rec_ids, strict=True))
        sess.store.save_canvas(sess.h, ctx.canvas)
    return rec_ids


@router.post("/chat")
def chat(body: ChatIn, request: Request, sess: Session = Depends(current)) -> StreamingResponse:
    st_ = sess.state
    s = st_.settings
    if len(body.message) > s.max_message_chars:
        raise HTTPException(
            422, {"code": "too_long", "message": f"Messages are limited to {s.max_message_chars} characters."}
        )
    if not st_.llm_enabled or st_.llm_paused():
        raise HTTPException(503, {"code": "no_llm", "message": "Chat is off right now. Use the form to compare plans."})
    q = st_.quotas
    if q is not None:
        try:
            q.before_turn(sess.h.id_hash)
        except QuotaExceeded as e:
            raise HTTPException(429, {"code": e.code, "message": e.message}) from e
        except BudgetExceeded as e:
            raise HTTPException(429, {"code": "budget", "message": str(e)}) from e
    profile = sess.store.load_profile(sess.h) or Profile()
    history = [m.to_chat() for m in sess.store.load_chat(sess.h)]
    canvas = sess.store.load_canvas(sess.h)
    ctx = tool_context(sess, profile, canvas)
    if q is not None:
        ip_hash = q.ip_hash(client_ip(request)) if sess.h.mode == "saved" else None
        orch = Orchestrator(
            st_.providers,
            budget_check=q.budget_check,
            usage_sink=lambda p, m, u: q.record(sess.h.mode, sess.h.id_hash, ip_hash, p, m, u),
        )
    else:
        orch = Orchestrator(st_.providers)
    try:
        res = orch.run_turn(ctx, history, body.message)
    except BudgetExceeded as e:
        raise HTTPException(429, {"code": "budget", "message": str(e) or "Chat is paused. Use the form."}) from e
    except ProviderError as e:
        log.warning("llm error: %s", type(e).__name__)
        raise HTTPException(
            503,
            {
                "code": "llm_unavailable",
                "message": "The assistant is unavailable right now. Use the form to compare plans.",
            },
        ) from e
    rec_ids = persist_turn(sess, body.message, res, ctx.profile)

    def events() -> Iterator[str]:
        yield _sse(
            "meta",
            {
                "model": res.model_id,
                "provider": res.provider,
                "prompt_version": res.prompt_version,
                "validation": res.validation,
            },
        )
        for chunk in _chunks(res.text):
            yield _sse("delta", {"text": chunk})
        yield _sse("canvas", res.canvas)
        if res.profile_changed:
            yield _sse("profile", ctx.profile.model_dump(mode="json"))
        yield _sse("done", {"citations": res.citations, "recommendation_ids": rec_ids})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


# ------------------------------------------------------------------ no-LLM comparison


class CompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Profile | None = None
    limit: int = Field(default=3, ge=1, le=5)


@router.post("/compare")
def compare_endpoint(body: CompareIn, sess: Session = Depends(current)) -> dict[str, Any]:
    """The no-LLM mode (DESIGN §8.2, §9): the intake form → the ranked table, with no model involved. Works when
    chat is off, paused by the budget, or over a session quota."""
    profile = body.profile
    if profile is not None:
        sess.store.save_profile(sess.h, profile)
    else:
        profile = sess.store.load_profile(sess.h) or Profile()
    canvas = sess.store.load_canvas(sess.h)
    ctx = tool_context(sess, profile, canvas)
    out = T.execute(ctx, ToolCall("form", "compare_plans", {"limit": body.limit}))
    if "error" in out:
        raise HTTPException(422, {"code": out["error"], "message": out.get("user_message", "Check the form.")})
    sess.store.save_canvas(sess.h, ctx.canvas)
    rec_ids = save_top(sess, ctx, profile)
    return {
        "canvas": ctx.canvas,
        "top": out["top"],
        "checklist": out["checklist"],
        "approximation_notes": out["approximation_notes"],
        "data_vintage": ctx.data_vintage(),
        "recommendation_ids": rec_ids,
        "disclaimer": ESTIMATE_DISCLAIMER,
    }
