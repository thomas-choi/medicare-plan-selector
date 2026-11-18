"""Saved-mode session store (DESIGN §5, §8.1): MySQL rows; ZIP, drugs, providers and chat content AES-GCM encrypted
with `PROFILE_ENC_KEY` (`key_version` per row). Canvas UI state is kept in Redis (`sav:{sid_hash}:canvas`, encrypted
with the same key, TTL = retention) because the schema has no canvas table; the plan rows are recomputed anyway.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import redis
from sqlalchemy import Connection, Engine, delete, func, insert, select, update

from selector import crypto
from selector import models as m
from selector.profile import Profile
from selector.store.base import SessionExpired, SessionHandle, SessionMeta, StoredMessage, dumps, now_utc

SAV_PREFIX = "sav:"


def _naive(t: dt.datetime) -> dt.datetime:
    return t.replace(tzinfo=None)


class MySQLSessionStore:
    mode = "saved"

    def __init__(self, engine: Engine, r: redis.Redis, key: bytes, key_version: int, retention_days: int) -> None:
        self.engine = engine
        self.r = r
        self.key = key
        self.key_version = key_version
        self.retention = dt.timedelta(days=retention_days)

    def _enc(self, h: SessionHandle, field: str, value: Any) -> bytes:
        return crypto.encrypt(self.key, dumps(value), f"{h.id_hash}:{field}".encode())

    def _dec(self, h: SessionHandle, field: str, blob: bytes | None) -> Any:
        if blob is None:
            return None
        return json.loads(crypto.decrypt(self.key, bytes(blob), f"{h.id_hash}:{field}".encode()))

    def _live(self, c: Connection, h: SessionHandle) -> Any:
        row = (
            c.execute(select(m.session).where(m.session.c.id_hash == h.id_hash, m.session.c.deleted_at.is_(None)))
            .mappings()
            .first()
        )
        if row is None or row["expires_at"] < _naive(now_utc()):
            raise SessionExpired("no saved session")
        return row

    def create(self, h: SessionHandle, meta: SessionMeta, ip_prefix_hash: str | None = None) -> None:
        now = now_utc()
        exp = now + self.retention
        meta.expires_at = exp.isoformat()
        with self.engine.begin() as c:
            c.execute(
                insert(m.session).values(
                    id_hash=h.id_hash,
                    created_at=_naive(now),
                    last_seen_at=_naive(now),
                    expires_at=_naive(exp),
                    consent_version=meta.consent_version,
                    consent_profile=meta.consent_profile,
                    consent_feedback_phi=meta.consent_feedback_phi,
                    plan_year=meta.plan_year,
                    ip_prefix_hash=ip_prefix_hash,
                )
            )
            c.execute(
                insert(m.consent_log).values(
                    session_id=h.id_hash,
                    consent_version=meta.consent_version,
                    choice_json={
                        "mode": "saved",
                        "profile": meta.consent_profile,
                        "feedback_phi": meta.consent_feedback_phi,
                    },
                    created_at=_naive(now),
                )
            )

    def get_meta(self, h: SessionHandle) -> SessionMeta | None:
        try:
            with self.engine.connect() as c:
                r = self._live(c, h)
        except SessionExpired:
            return None
        return SessionMeta(
            "saved",
            r["created_at"].isoformat(),
            r["expires_at"].isoformat(),
            r["consent_version"],
            r["plan_year"],
            bool(r["consent_profile"]),
            bool(r["consent_feedback_phi"]),
        )

    def touch(self, h: SessionHandle) -> None:
        now = now_utc()
        with self.engine.begin() as c:
            self._live(c, h)
            c.execute(
                update(m.session)
                .where(m.session.c.id_hash == h.id_hash)
                .values(last_seen_at=_naive(now), expires_at=_naive(now + self.retention))
            )

    def load_profile(self, h: SessionHandle) -> Profile | None:
        with self.engine.connect() as c:
            self._live(c, h)
            r = c.execute(select(m.profile).where(m.profile.c.session_id == h.id_hash)).mappings().first()
        if r is None:
            return None
        base = {
            "path": r["path"] or "both",
            **(r["utilization_json"] or {}),
            "must_haves": r["must_haves_json"] or {},
            **(r["budget_json"] or {}),
        }
        base.update(self._dec(h, "zip", r["zip_enc"]) or {})
        base["drugs"] = self._dec(h, "drugs", r["drugs_enc"]) or []
        base["providers"] = self._dec(h, "providers", r["providers_enc"]) or []
        return Profile.model_validate(base)

    def save_profile(self, h: SessionHandle, profile: Profile) -> None:
        d = profile.model_dump(mode="json")
        values = {
            "county_fips": None,
            "path": d["path"],
            "budget_json": {"weights": d["weights"]},
            "utilization_json": {
                "utilization": d["utilization"],
                "pharmacy_preference": d["pharmacy_preference"],
                "snp_eligible": d["snp_eligible"],
            },
            "must_haves_json": d["must_haves"],
            # Location and plan choice are encrypted with the ZIP: together they narrow down where someone lives.
            "zip_enc": self._enc(
                h, "zip", {k: d[k] for k in ("zip", "county_ssa", "county_name", "state", "current_plan_key")}
            ),
            "drugs_enc": self._enc(h, "drugs", d["drugs"]),
            "providers_enc": self._enc(h, "providers", d["providers"]),
            "key_version": self.key_version,
        }
        with self.engine.begin() as c:
            self._live(c, h)
            exists = c.execute(select(m.profile.c.session_id).where(m.profile.c.session_id == h.id_hash)).first()
            if exists:
                c.execute(update(m.profile).where(m.profile.c.session_id == h.id_hash).values(**values))
            else:
                c.execute(insert(m.profile).values(session_id=h.id_hash, **values))
        self.touch(h)

    def load_chat(self, h: SessionHandle) -> list[StoredMessage]:
        with self.engine.connect() as c:
            self._live(c, h)
            rows = c.execute(
                select(m.chat_msg).where(m.chat_msg.c.session_id == h.id_hash).order_by(m.chat_msg.c.seq)
            ).mappings()
            out = []
            for r in rows:
                body = self._dec(h, f"chat:{r['seq']}", r["content_enc"])
                out.append(
                    StoredMessage(
                        r["role"],
                        body["content"],
                        r["created_at"].isoformat(),
                        r["model_id"],
                        body.get("citations", []),
                    )
                )
        return out

    def append_chat(self, h: SessionHandle, msgs: list[StoredMessage], tokens: tuple[int, int] = (0, 0)) -> None:
        with self.engine.begin() as c:
            self._live(c, h)
            seq = c.execute(
                select(func.coalesce(func.max(m.chat_msg.c.seq), 0)).where(m.chat_msg.c.session_id == h.id_hash)
            ).scalar_one()
            for i, msg in enumerate(msgs, start=1):
                n = int(seq) + i
                c.execute(
                    insert(m.chat_msg).values(
                        session_id=h.id_hash,
                        seq=n,
                        role=msg.role,
                        content_enc=self._enc(h, f"chat:{n}", {"content": msg.content, "citations": msg.citations}),
                        key_version=self.key_version,
                        tool_calls_json=None,
                        model_id=msg.model_id,
                        tokens_in=tokens[0] if msg.role == "assistant" else None,
                        tokens_out=tokens[1] if msg.role == "assistant" else None,
                        created_at=_naive(now_utc()),
                    )
                )
        self.touch(h)

    def _canvas_key(self, h: SessionHandle) -> str:
        return f"{SAV_PREFIX}{h.id_hash}:canvas"

    def load_canvas(self, h: SessionHandle) -> dict[str, Any]:
        blob = self.r.get(self._canvas_key(h))
        if blob is None:
            return {}
        try:
            out: dict[str, Any] = json.loads(crypto.decrypt(self.key, bytes(blob), self._canvas_key(h).encode()))  # type: ignore[arg-type]
        except crypto.CryptoError:
            return {}
        return out

    def save_canvas(self, h: SessionHandle, canvas: dict[str, Any]) -> None:
        k = self._canvas_key(h)
        self.r.set(k, crypto.encrypt(self.key, dumps(canvas), k.encode()), ex=int(self.retention.total_seconds()))

    def save_recommendations(self, h: SessionHandle, rows: list[dict[str, Any]], data_vintage: str) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as c:
            self._live(c, h)
            for r in rows:
                res = c.execute(
                    insert(m.recommendation).values(
                        session_id=h.id_hash,
                        plan_year=r.get("plan_year", 2027),
                        rank_pos=r["rank"],
                        plan_key=r["plan_key"],
                        est_total_cents=r["total_est_cents"],
                        worst_case_cents=r["worst_case_cents"] if r["worst_case_cents"] is not None else -1,
                        weights_json=r.get("weights", {}),
                        data_vintage=data_vintage[:64],
                        created_at=_naive(now_utc()),
                    )
                )
                pk = res.inserted_primary_key
                ids.append(str(pk[0]) if pk else "")
        return ids

    def end_soon(self, h: SessionHandle, grace_seconds: int) -> None:
        """Saved sessions are kept on tab close (that is what Saved means)."""

    def delete(self, h: SessionHandle) -> int:
        """Delete my data: profile, chat, consent log, usage ledger, encrypted feedback text and the session row.
        Redacted feedback and `recommendation` rows (no PHI) stay, unlinked (`session_id` set to NULL)."""
        with self.engine.begin() as c:
            n = 0
            n += c.execute(
                update(m.feedback)
                .where(m.feedback.c.session_id == h.id_hash)
                .values(text_raw_enc=None, key_version=None, session_id=None)
            ).rowcount
            n += c.execute(
                update(m.recommendation).where(m.recommendation.c.session_id == h.id_hash).values(session_id=None)
            ).rowcount
            for t in (m.chat_msg, m.profile, m.consent_log):
                n += c.execute(delete(t).where(t.c.session_id == h.id_hash)).rowcount
            n += c.execute(delete(m.usage_ledger).where(m.usage_ledger.c.session_id_hash == h.id_hash)).rowcount
            n += c.execute(delete(m.session).where(m.session.c.id_hash == h.id_hash)).rowcount
        self.r.delete(self._canvas_key(h))
        return n


def purge_expired(
    conn: Connection, retention_days: int, feedback_retention_days: int, now: dt.datetime | None = None
) -> dict[str, int]:
    """Nightly retention purge (DESIGN §8.1, Q4): Saved sessions idle > RETENTION_DAYS (with their profile, chat,
    consent log and usage ledger) and feedback older than FEEDBACK_RETENTION_DAYS."""
    now_n = _naive(now or now_utc())
    cutoff = now_n - dt.timedelta(days=retention_days)
    ids = [r[0] for r in conn.execute(select(m.session.c.id_hash).where(m.session.c.last_seen_at < cutoff)).all()]
    out = {"sessions": 0, "feedback": 0}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        conn.execute(
            update(m.feedback)
            .where(m.feedback.c.session_id.in_(chunk))
            .values(text_raw_enc=None, key_version=None, session_id=None)
        )
        conn.execute(update(m.recommendation).where(m.recommendation.c.session_id.in_(chunk)).values(session_id=None))
        for t in (m.chat_msg, m.profile, m.consent_log):
            conn.execute(delete(t).where(t.c.session_id.in_(chunk)))
        conn.execute(delete(m.usage_ledger).where(m.usage_ledger.c.session_id_hash.in_(chunk)))
        out["sessions"] += conn.execute(delete(m.session).where(m.session.c.id_hash.in_(chunk))).rowcount
    fcut = now_n - dt.timedelta(days=feedback_retention_days)
    out["feedback"] = conn.execute(delete(m.feedback).where(m.feedback.c.created_at < fcut)).rowcount
    return out
