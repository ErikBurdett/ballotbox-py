"""
Canonical resolution for ``Jurisdiction`` rows used by ingestion and public URLs.

Ballotpedia and Democracy Works can otherwise create multiple rows for the same county
or city when casing, spacing, or the ``county`` stem field drifts slightly.
"""

from __future__ import annotations

from django.db.models import Q

from apps.geo.models import Jurisdiction, JurisdictionType


def _norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def canonical_county_name_and_stem(raw_name: str) -> tuple[str, str]:
    """Return ``(display_name, county_stem)`` for a US county label."""
    raw = _norm_ws(str(raw_name or "").strip())
    if not raw:
        return "", ""
    lower = raw.lower()
    if lower.endswith(" county"):
        county_label = raw
        stem = raw[: -len(" County")].strip() or raw
    else:
        stem = raw
        county_label = f"{raw} County"
    return county_label, stem


def get_or_create_canonical_county(*, state: str, raw_name: str) -> Jurisdiction:
    st = (state or "").strip().upper()
    county_label, stem = canonical_county_name_and_stem(raw_name)
    if not county_label or not st or len(st) != 2:
        raise ValueError("Invalid county name or state")

    qs = Jurisdiction.objects.filter(state=st, jurisdiction_type=JurisdictionType.COUNTY).filter(
        Q(name__iexact=county_label)
        | Q(name__iexact=f"{stem} County")
        | Q(name__iexact=stem)
        | Q(county__iexact=stem)
    )
    existing = qs.order_by("id").first()
    if existing:
        dirty = []
        if existing.name != county_label:
            existing.name = county_label
            dirty.append("name")
        if existing.county != stem:
            existing.county = stem
            dirty.append("county")
        if existing.city:
            existing.city = ""
            dirty.append("city")
        if dirty:
            existing.save(update_fields=dirty + ["updated_at"])
        return existing

    return Jurisdiction.objects.create(
        state=st,
        jurisdiction_type=JurisdictionType.COUNTY,
        name=county_label,
        county=stem,
        city="",
    )


def canonical_city_name(raw_name: str) -> str:
    return _norm_ws(str(raw_name or "").strip())


def get_or_create_canonical_city(*, state: str, raw_name: str, jurisdiction_type: str = JurisdictionType.CITY) -> Jurisdiction:
    st = (state or "").strip().upper()
    name = canonical_city_name(raw_name)
    if not name or not st or len(st) != 2:
        raise ValueError("Invalid city name or state")

    existing = (
        Jurisdiction.objects.filter(state=st, jurisdiction_type=jurisdiction_type)
        .filter(Q(name__iexact=name) | Q(city__iexact=name))
        .order_by("id")
        .first()
    )
    if existing:
        dirty = []
        if existing.name != name:
            existing.name = name
            dirty.append("name")
        if existing.city != name:
            existing.city = name
            dirty.append("city")
        if existing.county and existing.jurisdiction_type == JurisdictionType.CITY:
            # Keep parent county on file when present; only normalize name/city.
            pass
        if dirty:
            existing.save(update_fields=dirty + ["updated_at"])
        return existing

    return Jurisdiction.objects.create(
        state=st,
        jurisdiction_type=jurisdiction_type,
        name=name,
        county="",
        city=name,
    )


def dedupe_jurisdictions_queryset_by_url_slug(qs):
    """Return a list of jurisdictions with at most one row per ``(state, type, url_slug())``."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Jurisdiction] = []
    for j in qs.order_by("name", "id"):
        key = (j.state, j.jurisdiction_type, j.url_slug().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out
