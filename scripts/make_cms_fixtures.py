#!/usr/bin/env python3
"""Cut small public fixture samples (≤ 200 data rows per file) from the raw 2027 CMS files.

Usage: python3 -I scripts/make_cms_fixtures.py data/raw/2027 backend/tests/fixtures/cms/2027
Selection: a handful of Arizona plans (incl. golden H0028_028_0), their counties and a fixed drug list.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

PLANS = {
    "H0028_028_0",  # golden: Humana Gold Plus HMO (MA-PD), Maricopa
}
MAX_ROWS = 200
AZ = "Arizona"
EXTRA_SSA = {"02013", "05201", "05200"}  # Alaska (pending FIPS), LA partial + main code
DRUG_RXCUIS = {"861007", "617314", "1373463", "285018", "311040", "197361"}  # chosen below if present


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write(out: Path, name: str, header: list[str], rows: list[list[str]], delim: str, manifest: dict) -> None:
    assert len(rows) <= MAX_ROWS, (name, len(rows))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    w.writerows(rows)
    (out / name).write_text(buf.getvalue(), encoding="utf-8")
    manifest["files"][name] = {"rows": len(rows)}


def read(path: Path, delim: str, enc: str = "cp1252") -> tuple[list[str], list[list[str]]]:
    with path.open(encoding=enc, newline="") as f:
        r = list(csv.reader(f, delimiter=delim))
    return r[0], r[1:]


def key(contract: str, plan: str, seg: str) -> str:
    return f"{contract}_{int(plan):03d}_{int(seg or 0)}"


def main(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    lock = json.loads((raw.parents[1].parent / "sources.lock").read_text())["2027"]
    manifest: dict = {"note": "Public CMS/Census samples, ≤200 rows each; see docs/DATA-SOURCES.md",
                      "sources": {k: {"url": v["url"], "vintage": v["vintage"], "sha256": v["sha256"]}
                                  for k, v in lock.items()}, "files": {}}

    # Landscape: choose plans in Maricopa (golden + MA-only + PPO + SNP + 2 PDPs + regional PPO if any).
    z = zipfile.ZipFile(next((raw / "S1").glob("*.zip")))
    text = z.read("CY2027_Landscape_202611/CY2027_Landscape_202611.csv").decode("utf-8-sig")
    lh, lrows = (lambda r: (r[0], r[1:]))(list(csv.reader(io.StringIO(text))))
    ix = {h: i for i, h in enumerate(lh)}
    def pick(pred, n=1):
        found = []
        for r in lrows:
            k = r[ix["Contract Plan Segment ID"]]
            if k not in PLANS and k not in found and pred(r):
                found.append(k)
                if len(found) == n:
                    break
        PLANS.update(found)
    maricopa = lambda r: r[ix["State Territory Name"]] == AZ and r[ix["County Name"]] == "Maricopa"
    pick(lambda r: maricopa(r) and r[ix["Contract Category Type"]] == "MA")
    pick(lambda r: maricopa(r) and r[ix["Contract Category Type"]] == "MA-PD" and r[ix["Plan Type"]] == "PPO")
    pick(lambda r: maricopa(r) and r[ix["Contract Category Type"]] == "SNP")
    pick(lambda r: r[ix["State Territory Name"]] == AZ and r[ix["Contract Category Type"]] == "PDP", n=2)
    pick(lambda r: r[ix["State Territory Name"]] == AZ and r[ix["Plan Type"]] == "Regional PPO")
    sel = [r for r in lrows if r[ix["Contract Plan Segment ID"]] in PLANS
           and r[ix["State Territory Name"]] in (AZ,)]
    write(out, "landscape.csv", lh, sel, ",", manifest)
    manifest["plans"] = sorted(PLANS)

    # S3 members
    s3 = raw / "S3" / "members"
    def s3file(prefix: str) -> Path:
        return next(p for p in s3.iterdir() if p.name.lower().startswith(prefix) and "sample" not in p.name.lower())
    gh, grows = read(s3file("geographic locator"), "|")
    geo = [r for r in grows if r[1] == AZ or r[0] in EXTRA_SSA]
    write(out, "geo.txt", gh, geo, "|", manifest)
    az_ssa = {r[0] for r in geo}

    ph, prows = read(s3file("plan information"), "|")
    pinfo = [r for r in prows if key(r[0], r[1], r[2]) in PLANS and (r[11] in az_ssa or not r[11].strip())]
    write(out, "plan_info.txt", ph, pinfo, "|", manifest)
    fids = {r[5] for r in pinfo}

    fh, frows = read(s3file("basic drugs formulary"), "|")
    rx_by_fid: dict[str, set[str]] = {}
    for r in frows:
        if r[0] in fids:
            rx_by_fid.setdefault(r[0], set()).add(r[3])
    common = set.intersection(*rx_by_fid.values()) if rx_by_fid else set()
    chosen = sorted(common & DRUG_RXCUIS) or sorted(common)[:6]
    form = [r for r in frows if r[0] in fids and r[3] in chosen]
    write(out, "formulary.txt", fh, form[:MAX_ROWS], "|", manifest)
    manifest["rxcuis"] = chosen

    for name, prefix in (("cost.txt", "beneficiary cost"), ("insulin.txt", "insulin beneficiary")):
        hh, rr = read(s3file(prefix), "|")
        write(out, name, hh, [r for r in rr if key(r[0], r[1], r[2]) in PLANS], "|", manifest)

    # S2 PBP
    pz = zipfile.ZipFile(next((raw / "S2").glob("*.zip")))
    for name, member in (("plan_area.txt", "PlanArea.txt"), ("b7.txt", "pbp_b7_health_prof.txt"),
                         ("b4.txt", "pbp_b4_emerg_urgent.txt"), ("b9.txt", "pbp_b9_outpat_hosp.txt"),
                         ("b1a.txt", "pbp_b1a_inpat_hosp.txt")):
        rows = list(csv.reader(io.StringIO(pz.read(member).decode("cp1252")), delimiter="\t"))
        h = rows[0]
        keep = [r for r in rows[1:] if key(r[0], r[1], r[2]) in PLANS]
        if name == "plan_area.txt":
            keep = [r for r in keep if r[10] in az_ssa]
        write(out, name, h, keep, "\t", manifest)

    # Crosswalk + Census samples
    xz = zipfile.ZipFile(next((raw / "XW1").glob("*.zip")))
    xrows = list(csv.reader(io.StringIO(xz.read(
        "State_County_Penetration_MA_2026_11/State_County_Penetration_MA_2026_11.csv").decode("cp1252"))))
    keepx = [[*r[:8], "", "", ""] for r in xrows[1:] if r[7] in az_ssa]  # geography only, no enrollment counts
    write(out, "penetration.csv", xrows[0], keepx, ",", manifest)
    census = (raw / "XW2" / "national_county2020.txt").read_text(encoding="utf-8").splitlines()
    ovs = {l.split(",")[1] for l in (raw.parents[2] / "sources" / "ssa_fips_overrides.csv").read_text().splitlines()[1:]}
    keepc = [l.split("|") for l in census[1:] if l.startswith("AZ|") or (l.split("|")[1] + l.split("|")[2]) in ovs]
    write(out, "census_county.txt", census[0].split("|"), keepc, "|", manifest)

    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["files"], indent=1), manifest["plans"], manifest["rxcuis"])


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
