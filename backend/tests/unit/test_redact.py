"""PHI redactor (DESIGN §7)."""

from __future__ import annotations

import pytest

from selector.redact import redact


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("My Ozempic costs too much", "Ozempic"),
        ("atorvastatin and lisinopril", "atorvastatin"),
        ("taking rosuvastatin", "rosuvastatin"),  # also by stem
        ("Dr. Jane Smith is my doctor", "Jane"),
        ("dr smith", "smith"),
        ("call 602-555-1212", "555"),
        ("call (602) 555-1212", "555"),
        ("mail me at jane.doe@example.com", "jane.doe"),
        ("born 03/04/1955", "1955"),
        ("born March 3, 1955", "1955"),
        ("I live in 85004", "85004"),
        ("NPI 1234567890", "1234567890"),
        ("MBI 1EG4-TE5-MK73", "1EG4"),
        ("SSN 123-45-6789", "6789"),
    ],
)
def test_redacts(text: str, gone: str) -> None:
    assert gone not in redact(text)


def test_extra_terms_from_the_users_profile() -> None:
    assert "zzfakedrug" not in redact("zzfakedrug is pricey", ["zzfakedrug"]).lower()


def test_keeps_ordinary_feedback() -> None:
    t = "The table was confusing and the premium of $0 looked wrong for plan H0028_028_0."
    assert redact(t) == t
