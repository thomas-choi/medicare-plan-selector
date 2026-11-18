"""App quotas and cost accounting (DESIGN §8.2, §8.5 Cost ledger).

Redis counters (no persistence; they reset on a Redis restart, which only ever makes limits looser for a day):
- `quota:ip:{hmac}:{day}`: new sessions per IP prefix per UTC day. The HMAC key is a random salt kept in Redis
  for the day (`quota:salt:{day}`, 48 h TTL), optionally peppered with `IP_HASH_SECRET`, so the hash rotates daily
  and can't be reversed from a dump after the salt is gone. IPv4 uses the /24, IPv6 the /48.
- `quota:sess:{sid_hash}:turns|tokens`: chat turns and LLM tokens per session (TTL 2 days).
- `quota:budget:{day}`: estimated LLM spend in micro-USD for the UTC day. Seeded from `usage_daily` if Redis lost it.

MySQL: `usage_daily` (all modes, no session or IP linkage) and `usage_ledger` (Saved mode only).
When the daily budget is spent, chat pauses (`BudgetExceeded`) and the no-LLM form keeps working.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import ipaddress
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import redis
from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from selector import models as m
from selector.agent.orchestrator import BudgetExceeded
from selector.agent.providers import Usage
from selector.config import Settings

SESSION_COUNTER_TTL = 2 * 86400


class QuotaExceeded(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def ip_prefix(ip: str | None) -> str:
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return "unknown"
    bits = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))


@dataclass
class Quotas:
    r: redis.Redis
    engine: Engine
    settings: Settings
    clock: Callable[[], float] = time.time

    # ------------------------------------------------------------ helpers
    def day(self) -> dt.date:
        return dt.datetime.fromtimestamp(self.clock(), dt.UTC).date()

    def _salt(self) -> bytes:
        k = f"quota:salt:{self.day().isoformat()}"
        self.r.set(k, os.urandom(32).hex(), nx=True, ex=2 * 86400)
        salt = self.r.get(k) or b""
        pepper = self.settings.ip_hash_secret.get_secret_value().encode()
        return hashlib.sha256(bytes(salt) + pepper).digest()  # type: ignore[arg-type]

    def ip_hash(self, ip: str | None) -> str:
        return hmac.new(self._salt(), ip_prefix(ip).encode(), hashlib.sha256).hexdigest()

    def cost_micro_usd(self, u: Usage) -> int:
        s = self.settings
        # $/Mtok × tokens = micro-USD exactly.
        return round(u.tokens_in * s.llm_price_in_per_mtok_usd + u.tokens_out * s.llm_price_out_per_mtok_usd)

    # ------------------------------------------------------------ sessions per IP
    def on_new_session(self, ip: str | None) -> str:
        """Count a new session for this IP prefix; raises QuotaExceeded over `MAX_SESSIONS_PER_IP_PER_DAY`."""
        h = self.ip_hash(ip)
        k = f"quota:ip:{h}:{self.day().isoformat()}"
        n = int(self.r.incr(k))
        if n == 1:
            self.r.expire(k, 86400)
        if n > self.settings.max_sessions_per_ip_per_day:
            raise QuotaExceeded("ip_sessions", "Too many new sessions from your network today. Try again tomorrow.")
        return h

    # ------------------------------------------------------------ per-session chat limits
    def _sk(self, sid_hash: str, what: str) -> str:
        return f"quota:sess:{sid_hash}:{what}"

    def session_usage(self, sid_hash: str) -> tuple[int, int]:
        turns, tokens = self.r.mget(self._sk(sid_hash, "turns"), self._sk(sid_hash, "tokens"))
        return int(turns or 0), int(tokens or 0)

    def before_turn(self, sid_hash: str) -> None:
        s = self.settings
        turns, tokens = self.session_usage(sid_hash)
        if turns >= s.max_turns_per_session:
            raise QuotaExceeded(
                "session_turns", "You've reached the chat limit for this session. The comparison form still works."
            )
        if tokens >= s.max_tokens_per_session:
            raise QuotaExceeded(
                "session_tokens", "You've reached the chat limit for this session. The comparison form still works."
            )
        self.budget_check()
        k = self._sk(sid_hash, "turns")
        self.r.incr(k)
        self.r.expire(k, SESSION_COUNTER_TTL)

    # ------------------------------------------------------------ global budget
    def _budget_key(self) -> str:
        return f"quota:budget:{self.day().isoformat()}"

    def spent_micro_usd(self) -> int:
        raw = self.r.get(self._budget_key())
        if raw is None:
            with self.engine.connect() as c:
                total = c.execute(
                    select(func.coalesce(func.sum(m.usage_daily.c.cost_micro_usd), 0)).where(
                        m.usage_daily.c.day == self.day()
                    )
                ).scalar_one()
            self.r.set(self._budget_key(), int(total), nx=True, ex=2 * 86400)
            return int(total)
        return int(raw)

    def budget_left_usd(self) -> float:
        return self.settings.llm_daily_budget_usd - self.spent_micro_usd() / 1_000_000

    def paused(self) -> bool:
        return self.budget_left_usd() <= 0

    def budget_check(self) -> None:
        if self.paused():
            raise BudgetExceeded("Chat is paused for today (cost limit reached). The comparison form still works.")

    # ------------------------------------------------------------ accounting
    def record(self, mode: str, sid_hash: str, ip_hash: str | None, provider: str, model: str, u: Usage) -> None:
        cost = self.cost_micro_usd(u)
        tk = self._sk(sid_hash, "tokens")
        self.r.incrby(tk, u.tokens_in + u.tokens_out)
        self.r.expire(tk, SESSION_COUNTER_TTL)
        self.spent_micro_usd()  # make sure the day's key is seeded before adding
        self.r.incrby(self._budget_key(), cost)
        day = self.day()
        stmt = mysql_insert(m.usage_daily).values(
            day=day,
            provider=provider[:32],
            model=model[:128],
            mode=mode,
            tokens_in=u.tokens_in,
            tokens_out=u.tokens_out,
            cost_micro_usd=cost,
        )
        stmt = stmt.on_duplicate_key_update(
            tokens_in=m.usage_daily.c.tokens_in + stmt.inserted.tokens_in,
            tokens_out=m.usage_daily.c.tokens_out + stmt.inserted.tokens_out,
            cost_micro_usd=m.usage_daily.c.cost_micro_usd + stmt.inserted.cost_micro_usd,
        )
        with self.engine.begin() as c:
            c.execute(stmt)
            if mode == "saved":
                c.execute(
                    m.usage_ledger.insert().values(
                        day=day,
                        session_id_hash=sid_hash,
                        ip_prefix_hash=ip_hash,
                        provider=provider[:32],
                        model=model[:128],
                        tokens_in=u.tokens_in,
                        tokens_out=u.tokens_out,
                        cost_micro_usd=cost,
                    )
                )
