"""Post-load validation (DESIGN §4): counts, foreign-key coverage, golden rows. Any failure aborts the swap."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, bindparam, text


class ValidationFailed(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("ingest validation failed:\n  " + "\n  ".join(problems))
        self.problems = problems


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def validate_year(conn: Connection, year: int, spec: dict[str, Any], oop_thresholds: set[int]) -> list[str]:
    problems: list[str] = []
    y = {"y": year}
    for t in (
        "plan",
        "plan_county",
        "pbp_benefit",
        "formulary",
        "plan_formulary",
        "tier_cost",
        "part_d_params",
        "medicare_params",
    ):
        if _scalar(conn, f"SELECT COUNT(*) FROM `{t}` WHERE plan_year=:y", **y) == 0:  # noqa: S608
            problems.append(f"{t}: no rows for {year}")
    if _scalar(conn, "SELECT COUNT(*) FROM county") == 0:
        problems.append("county: empty")

    # Every MA-PD / MA / PDP plan has a service area; every service-area county exists.
    n = _scalar(
        conn,
        "SELECT COUNT(*) FROM plan p WHERE p.plan_year=:y AND p.category IN ('MAPD','MA','PDP') "
        "AND NOT EXISTS (SELECT 1 FROM plan_county pc WHERE pc.plan_year=p.plan_year AND pc.plan_key=p.plan_key)",
        **y,
    )
    if n:
        problems.append(f"{n} MA/MA-PD/PDP plans without a county")
    n = _scalar(
        conn,
        "SELECT COUNT(*) FROM plan_county pc LEFT JOIN county c ON c.ssa_code=pc.ssa_code "
        "WHERE pc.plan_year=:y AND c.ssa_code IS NULL",
        **y,
    )
    if n:
        problems.append(f"{n} plan_county rows reference unknown SSA counties")

    # Every MA-PD row maps to a FIPS county, except the approved pending states.
    pending = tuple(spec.get("pending_fips_states", [])) or ("",)
    rows = conn.execute(
        text(
            "SELECT DISTINCT c.state_name, c.name, c.ssa_code FROM plan_county pc "
            "JOIN plan p ON p.plan_year=pc.plan_year AND p.plan_key=pc.plan_key "
            "JOIN county c ON c.ssa_code=pc.ssa_code "
            "WHERE pc.plan_year=:y AND p.category='MAPD' AND c.fips IS NULL AND c.state_name NOT IN :pending"
        ).bindparams(bindparam("pending", expanding=True)),
        {"y": year, "pending": pending},
    ).all()
    if rows:
        problems.append(f"{len(rows)} MA-PD counties without FIPS outside pending states: {rows[:10]}")

    # DESIGN v0.5 B6 (AK4): no county may be left without a decision. `pending` is allowed only in the listed states;
    # a new pending county anywhere else (a new SSA code in the S3 locator) fails the ingest until it is mapped.
    rows = conn.execute(
        text(
            "SELECT state_name, name, ssa_code FROM county "
            "WHERE fips_status='pending' AND state_name NOT IN :pending ORDER BY ssa_code"
        ).bindparams(bindparam("pending", expanding=True)),
        {"pending": pending},
    ).all()
    if rows:
        problems.append(f"{len(rows)} counties with a pending SSA→FIPS mapping: {rows[:10]}")

    # DESIGN v0.5 B6.1 (AK5): a plan must never be served in a `retired` SSA area. Region-wide plans skip them at load
    # time, so a hit here is a plan whose own service area (PBP PlanArea) still names one: fail, never drop it silently.
    rows = conn.execute(
        text(
            "SELECT pc.plan_key, c.ssa_code, c.name FROM plan_county pc JOIN county c ON c.ssa_code=pc.ssa_code "
            "WHERE pc.plan_year=:y AND c.fips_status='retired' ORDER BY pc.plan_key, c.ssa_code"
        ),
        y,
    ).all()
    if rows:
        problems.append(f"{len(rows)} plan service-area rows use a retired SSA county: {rows[:10]}")

    # Part D plans need a formulary.
    n = _scalar(
        conn,
        "SELECT COUNT(*) FROM plan p WHERE p.plan_year=:y AND p.category IN ('MAPD','PDP') "
        "AND NOT p.part_d_suppressed "
        "AND NOT EXISTS (SELECT 1 FROM plan_formulary f WHERE f.plan_year=p.plan_year AND f.plan_key=p.plan_key)",
        **y,
    )
    if n:
        problems.append(f"{n} MA-PD/PDP plans without a formulary")

    # Every Medicare Advantage plan (anything but a PDP) has a dental row, even if it has no dental benefit.
    n = _scalar(
        conn,
        "SELECT COUNT(*) FROM plan p WHERE p.plan_year=:y AND p.category <> 'PDP' "
        "AND NOT EXISTS (SELECT 1 FROM plan_dental d WHERE d.plan_year=p.plan_year AND d.plan_key=p.plan_key)",
        **y,
    )
    if n:
        problems.append(f"{n} Medicare Advantage plans without a plan_dental row (PBP b16)")

    # The Landscape OOP threshold must equal the cited Part D parameter.
    oop = int(spec["params"]["part_d"]["oop_threshold_cents"])
    if oop_thresholds and oop_thresholds != {oop}:
        problems.append(f"Landscape OOP thresholds {sorted(oop_thresholds)} != part_d_params {oop}")

    for g in spec.get("golden", []):
        row = (
            conn.execute(
                text(
                    "SELECT part_c_premium_cents, part_d_deductible_cents, moop_in_network_cents, star_overall "
                    "FROM plan WHERE plan_year=:y AND plan_key=:k"
                ),
                {"y": year, "k": g["plan_key"]},
            )
            .mappings()
            .first()
        )
        if row is None:
            problems.append(f"golden {g['plan_key']}: missing")
            continue
        for col in ("part_c_premium_cents", "part_d_deductible_cents", "moop_in_network_cents"):
            if row[col] != g[col]:
                problems.append(f"golden {g['plan_key']}.{col}: {row[col]} != {g[col]}")
        if row["star_overall"] != Decimal(str(g["star_overall"])):
            problems.append(f"golden {g['plan_key']}.star_overall: {row['star_overall']} != {g['star_overall']}")
        if "county_ssa" in g and not _scalar(
            conn,
            "SELECT COUNT(*) FROM plan_county WHERE plan_year=:y AND plan_key=:k AND ssa_code=:s",
            y=year,
            k=g["plan_key"],
            s=g["county_ssa"],
        ):
            problems.append(f"golden {g['plan_key']}: not offered in county {g['county_ssa']}")
        if "dental" in g:
            drow = (
                conn.execute(
                    text("SELECT * FROM plan_dental WHERE plan_year=:y AND plan_key=:k"),
                    {"y": year, "k": g["plan_key"]},
                )
                .mappings()
                .first()
            )
            if drow is None:
                problems.append(f"golden {g['plan_key']}: no dental row")
            else:
                for col, want in g["dental"].items():
                    got = drow[col]
                    if (bool(got) if isinstance(want, bool) else got) != want:
                        problems.append(f"golden {g['plan_key']}.dental.{col}: {got} != {want}")
    return problems
