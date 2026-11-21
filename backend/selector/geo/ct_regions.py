"""Connecticut planning regions → legacy counties (DESIGN v0.5 B6).

Census replaced Connecticut's 8 counties with 9 planning regions (FIPS 09110–09190) in 2022, so a HUD ZIP→county row
can carry a planning-region code. CMS (S3 geo locator, Landscape, PBP) still keys plans by the 8 legacy counties
(SSA 07000–07070 ↔ FIPS 09001–09015, `sources/ssa_fips_overrides.csv`). A planning-region FIPS is therefore replaced
by the legacy county or counties its towns belong to. When a region spans several legacy counties, the ZIP gets every
one of them, so the user picks theirs in the existing county picker.

Source (S27, **V** 2026-11-21): Census "ct_cou_to_cousub_crosswalk.xlsx",
https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx
(sha256 f70c3ce6bac6e1e667ee29c150735224a9fb19d66edbdef17822ddc8006c238a). Counts are the file's county-subdivision
rows (towns; 174 in all) per legacy county; the counties are listed with the most first.
"""

from __future__ import annotations

# region FIPS → (region name, ((legacy county FIPS, legacy county name, towns), ...))
CT_PLANNING_REGIONS: dict[str, tuple[str, tuple[tuple[str, str, int], ...]]] = {
    "09110": ("Capitol Planning Region", (("09003", "Hartford", 26), ("09013", "Tolland", 12))),
    "09120": ("Greater Bridgeport Planning Region", (("09001", "Fairfield", 7),)),
    "09130": (
        "Lower Connecticut River Valley Planning Region",
        (("09007", "Middlesex", 16), ("09011", "New London", 2)),
    ),
    "09140": (
        "Naugatuck Valley Planning Region",
        (("09009", "New Haven", 12), ("09005", "Litchfield", 5), ("09001", "Fairfield", 1), ("09003", "Hartford", 1)),
    ),
    "09150": (
        "Northeastern Connecticut Planning Region",
        (("09015", "Windham", 14), ("09011", "New London", 1), ("09013", "Tolland", 1)),
    ),
    "09160": ("Northwest Hills Planning Region", (("09005", "Litchfield", 19), ("09003", "Hartford", 2))),
    "09170": ("South Central Connecticut Planning Region", (("09009", "New Haven", 16),)),
    "09180": ("Southeastern Connecticut Planning Region", (("09011", "New London", 19), ("09015", "Windham", 1))),
    "09190": ("Western Connecticut Planning Region", (("09001", "Fairfield", 17), ("09005", "Litchfield", 2))),
}  # fmt: skip

PICK_NOTE = (
    "Your ZIP code is in a Connecticut planning region that covers more than one county. "
    "Medicare plans still use the old counties: pick yours."
)


def legacy_fips(fips: str) -> list[str]:
    """The legacy county FIPS for a CT planning-region FIPS; any other FIPS is returned unchanged."""
    region = CT_PLANNING_REGIONS.get(fips)
    if region is None:
        return [fips]
    return [county for county, _, _ in region[1]]
