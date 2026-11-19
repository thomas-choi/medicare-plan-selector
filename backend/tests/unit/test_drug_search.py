"""Drug search regression (Thomas's ml3090 report 2026-11-19: "the drug search has no response").

Root cause: RxNav `drugs.json?name=` matches drug names only, so "tamsulosin 0.4 mg capsule" returned zero
candidates and the UI showed nothing. The client now falls back to the ingredient name, then to RxNav's
approximate match, and ranks the strength/form the user typed first. Fixtures are trimmed real RxNav answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from selector.lookups import LookupError_, RxNavClient, ingredient_query, normalize_drug_query

BASE = "https://rxnav.nlm.nih.gov/REST"
FX: dict[str, Any] = json.loads((Path(__file__).parents[1] / "fixtures/rxnav/tamsulosin.json").read_text())
TAMSULOSIN_CAPSULE = "863669"  # RxNorm SCD: tamsulosin hydrochloride 0.4 MG Oral Capsule (checked live 2026-11-19)


def client() -> RxNavClient:
    return RxNavClient(httpx.Client(), min_interval_s=0)


def mock_drugs(by_name: dict[str, str]) -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FX[by_name.get(request.url.params["name"], "drugs_empty")])

    return respx.get(f"{BASE}/drugs.json").mock(side_effect=handler)


@pytest.mark.parametrize(
    ("raw", "norm", "base"),
    [
        ("tamsulosin 0.4 mg capsule", "tamsulosin 0.4 mg capsule", "tamsulosin"),
        ("  Tamsulosin   0.4mg ", "tamsulosin 0.4 mg", "tamsulosin"),
        ("tamsulosin HCl 0.4 MG oral capsule", "tamsulosin hcl 0.4 mg oral capsule", "tamsulosin"),
        ("potassium chloride 10 meq ER tab", "potassium chloride 10 meq er tab", "potassium chloride"),
        ("tamsulosin", "tamsulosin", "tamsulosin"),
    ],
)
def test_query_normalization(raw: str, norm: str, base: str) -> None:
    assert normalize_drug_query(raw) == norm
    assert ingredient_query(raw) == base


@respx.mock
def test_full_string_falls_back_to_ingredient_and_ranks_the_capsule_first() -> None:
    route = mock_drugs({"tamsulosin": "drugs_tamsulosin"})
    res = client().find("tamsulosin 0.4 mg capsule")
    assert res.how == "ingredient" and res.matched_as == "tamsulosin"
    assert res.candidates[0].rxcui == TAMSULOSIN_CAPSULE
    assert [c.tty for c in res.candidates] and all(c.tty in ("SCD", "SBD", "GPCK", "BPCK") for c in res.candidates)
    assert [r.request.url.params["name"] for r in route.calls] == ["tamsulosin 0.4 mg capsule", "tamsulosin"]


@respx.mock
def test_partial_name_is_an_exact_search_with_single_ingredient_generics_first() -> None:
    mock_drugs({"tamsulosin": "drugs_tamsulosin"})
    res = client().find("tamsulosin")
    assert res.how == "exact" and res.matched_as is None
    rx = [c.rxcui for c in res.candidates]
    assert TAMSULOSIN_CAPSULE in rx
    assert rx.index(TAMSULOSIN_CAPSULE) < rx.index("863671")  # generic before brand
    assert rx[-1] in ("996097", "996101")  # combination products last
    assert "77492" not in rx  # ingredient-only concepts can't be priced


@respx.mock
def test_glued_strength_and_brand_order() -> None:
    mock_drugs({"tamsulosin": "drugs_tamsulosin"})
    res = client().find("Tamsulosin 0.4mg capsule")
    assert res.candidates[0].rxcui == TAMSULOSIN_CAPSULE


@respx.mock
def test_approximate_match_when_name_search_finds_nothing() -> None:
    mock_drugs({})
    respx.get(f"{BASE}/approximateTerm.json").mock(
        return_value=httpx.Response(200, json=FX["approximate_tamsulosin_capsule"])
    )
    props = respx.get(f"{BASE}/rxcui/863669/properties.json").mock(
        return_value=httpx.Response(200, json=FX["properties_863669"])
    )
    res = client().find("tamsulosn 0.4 capsule")
    assert res.how == "approximate" and res.candidates[0].rxcui == TAMSULOSIN_CAPSULE
    assert props.call_count == 1  # duplicate RxCUIs in the approximate answer are fetched once


@respx.mock
def test_nothing_found_is_explicit_and_cached() -> None:
    drugs = mock_drugs({})
    respx.get(f"{BASE}/approximateTerm.json").mock(return_value=httpx.Response(200, json={"approximateGroup": {}}))
    c = client()
    assert c.find("zzqx 5 mg").how == "none" and c.find("zzqx 5 mg").candidates == []
    assert drugs.call_count == 2  # the second find() is served from the cache


@respx.mock
def test_network_failure_raises_lookup_error() -> None:
    respx.get(f"{BASE}/drugs.json").mock(side_effect=httpx.ConnectTimeout("no route"))
    with pytest.raises(LookupError_):
        client().find("tamsulosin")


@respx.mock
def test_search_keeps_the_old_list_api_for_the_agent_tool() -> None:
    mock_drugs({"tamsulosin": "drugs_tamsulosin"})
    assert client().search("tamsulosin 0.4 mg capsule", limit=1)[0].rxcui == TAMSULOSIN_CAPSULE
