"""Versioned study definitions and auditable, approximate trip anchors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Anchor:
    name: str
    longitude: float
    latitude: float
    role: str = "mixed"


@dataclass(frozen=True)
class StudyArea:
    slug: str
    name: str
    bbox: tuple[float, float, float, float]
    anchors: tuple[Anchor, ...]
    sources: tuple[str, ...]


NH48 = StudyArea(
    "nh48_airport",
    "NH-48 · Mahipalpur–Shiv Murti–Rajokri",
    (77.085, 28.500, 77.160, 28.562),
    (
        Anchor("Mahipalpur area", 77.127, 28.548, "mixed"),
        Anchor("Shiv Murti approach area", 77.129, 28.536, "gateway"),
        Anchor("Rajokri area", 77.107, 28.512, "residential"),
        Anchor("Rangpuri area", 77.119, 28.530, "residential"),
        Anchor("Vasant Kunj western approach", 77.152, 28.535, "mixed"),
    ),
    (
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2132154",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2279818",
    ),
)
ROHINI = StudyArea("rohini", "Rohini / DTU approaches", (77.100, 28.735, 77.130, 28.762), (), ())
STUDIES = {s.slug: s for s in (NH48, ROHINI)}
