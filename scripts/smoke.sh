#!/usr/bin/env bash
# Smoke test against a running app (make app-up → http://127.0.0.1:8080, or make api-dev → http://127.0.0.1:8000).
# Needs `make ingest-dev` data. Uses a throwaway No-save session and erases it at the end. Prints no secrets.
set -euo pipefail
BASE="${1:-http://127.0.0.1:8080}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT
c() { curl -fsS -b "$JAR" -c "$JAR" "$@"; }
j() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }
pass() { printf '  ok  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; exit 1; }

echo "Smoke test against $BASE"
c "$BASE/api/health" | j 'assert d["status"]=="ok", d' && pass "GET /api/health" || fail "GET /api/health"
c "$BASE/api/config" | j 'assert d["plan_year"]==2027 and d["default_mode"] in ("nosave","saved"); print("      llm_enabled=%s provider=%s modes=%s" % (d["llm_enabled"], d["llm_provider_label"], d["modes"]))' \
  && pass "GET /api/config" || fail "GET /api/config" || fail "GET /api/config"
c -H 'Content-Type: application/json' -X POST "$BASE/api/session" \
  -d '{"mode":"nosave","consent_version":"2026-11-17","accept_terms":true}' | j 'assert d["session"]["mode"]=="nosave"' \
  && pass "POST /api/session (No-save)" || fail "POST /api/session" || fail "POST /api/session (No-save)"
c "$BASE/api/location?zip=85004" | j 'assert [x["ssa_code"] for x in d["counties"]]==["03060"], d' && pass "ZIP 85004 → Maricopa (SSA 03060)" || fail "ZIP 85004 → Maricopa (SSA 03060)"
c "$BASE/api/location?zip=85142" | j 'assert sorted(x["ssa_code"] for x in d["counties"])==["03060","03100"], d' \
  && pass "ZIP 85142 → Maricopa + Pinal (split ZIP)" || fail "ZIP 85142" || fail "ZIP 85142 → Maricopa + Pinal (split ZIP)"
PROFILE='{"profile":{"zip":"85004","county_ssa":"03060","county_name":"Maricopa","state":"AZ",
  "drugs":[{"name":"metformin","rxcui":"197361"},{"name":"brand drug","rxcui":"285018"}],"utilization":"medium"},"limit":3}'
c -H 'Content-Type: application/json' -X POST "$BASE/api/compare" -d "$PROFILE" | j '
rows={r["plan_key"]:r for r in d["canvas"]["rows"]}
g=rows["H0028_028_0"]
print("      plans=%d ranked=%d top=%s" % (len(rows), sum(1 for r in rows.values() if r["rank"]), [t["plan_key"] for t in d["top"]]))
print("      H0028_028_0: rank=%s premium=$%.2f/mo moop=$%.2f partD_ded=$%.2f stars=%s total=$%.2f-$%.2f" % (g["rank"], g["monthly_premium_cents"]/100, g["moop_cents"]/100, g["part_d_deductible_cents"]/100, g["star_overall"], g["total_low_cents"]/100, g["total_high_cents"]/100))
assert g["rank"]==1 and g["monthly_premium_cents"]==0 and g["moop_cents"]==655000 and g["part_d_deductible_cents"]==32500 and g["star_overall"]==4.5, g
assert g["total_low_cents"]==322855, g["total_low_cents"]
assert all(r.get("src_ref") for r in rows.values())' && pass "POST /api/compare: Maricopa ranked, golden H0028_028_0 row matches" \
  || fail "POST /api/compare (needs make ingest-dev)" || fail "POST /api/compare: Maricopa ranked, golden H0028_028_0 row matches"
if c "$BASE/api/config" | j 'sys.exit(0 if d["llm_enabled"] else 1)'; then
  c -H 'Content-Type: application/json' -X POST "$BASE/api/chat" -d '{"message":"Explain H0028_028_0"}' >"$JAR.sse"
  grep -q '^event: done' "$JAR.sse" && pass "POST /api/chat (SSE) completed" || fail "POST /api/chat (SSE)"
  rm -f "$JAR.sse"
else
  echo "  --  chat skipped (no-LLM mode)"
fi
c -X DELETE "$BASE/api/session" | j 'assert d["deleted"]' && pass "DELETE /api/session (erase)" || fail "DELETE /api/session (erase)"
if curl -s "$BASE/" | grep -q '<div id="root">'; then pass "GET / serves the web UI"; else echo "  --  GET / has no web UI (API only?)"; fi
echo "Smoke test passed."
