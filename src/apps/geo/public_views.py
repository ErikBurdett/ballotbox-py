from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.text import slugify

from apps.elections.models import Candidacy, Election, OfficeholderTerm, Race
from apps.ingestion.models import SourceRecord
from apps.offices.models import Office

from .jurisdiction_canonical import dedupe_jurisdictions_queryset_by_url_slug
from .models import District, Jurisdiction, JurisdictionType

_RACE_HUB_LIMIT = 200

_MUNICIPAL_TYPES = (
    JurisdictionType.CITY,
    JurisdictionType.TOWN,
    JurisdictionType.VILLAGE,
    JurisdictionType.BOROUGH,
    JurisdictionType.TOWNSHIP,
)


def _validate_us_state(state: str) -> str:
    state_u = state.upper().strip()
    if len(state_u) != 2 or not state_u.isalpha():
        raise Http404("Invalid state")
    return state_u


def canonical_jurisdiction_public_url(request, jurisdiction: Jurisdiction) -> str:
    """Prefer slug URLs for counties and municipal jurisdictions (SEO canonical)."""
    if jurisdiction.jurisdiction_type == JurisdictionType.COUNTY:
        path = reverse(
            "geo:county_detail",
            kwargs={"state": jurisdiction.state, "county_slug": jurisdiction.url_slug()},
        )
        return request.build_absolute_uri(path)
    if jurisdiction.jurisdiction_type in _MUNICIPAL_TYPES:
        path = reverse(
            "geo:city_detail",
            kwargs={"state": jurisdiction.state, "city_slug": jurisdiction.url_slug()},
        )
        return request.build_absolute_uri(path)
    return request.build_absolute_uri(request.path)


def resolve_county_jurisdiction(state: str, county_slug: str) -> Jurisdiction:
    """Resolve a county ``Jurisdiction`` from URL ``state`` and ``county_slug``."""
    state_u = _validate_us_state(state)
    want = county_slug.strip().lower()
    if not want:
        raise Http404("Invalid county")

    qs = Jurisdiction.objects.filter(state=state_u, jurisdiction_type=JurisdictionType.COUNTY)
    for j in qs:
        if j.url_slug().lower() == want:
            return j
    for j in qs:
        if j.county and slugify(j.county).lower() == want:
            return j
    for j in qs:
        stem = slugify(j.name.replace(" County", "").strip()).lower()
        if stem == want or f"{stem}-county" == want:
            return j
    raise Http404("County not found")


def resolve_city_jurisdiction(state: str, city_slug: str) -> Jurisdiction:
    """Resolve a municipal ``Jurisdiction`` (city, town, etc.) from URL slug."""
    state_u = _validate_us_state(state)
    want = city_slug.strip().lower()
    if not want:
        raise Http404("Invalid city")

    qs = Jurisdiction.objects.filter(state=state_u, jurisdiction_type__in=_MUNICIPAL_TYPES)
    for j in qs.order_by("jurisdiction_type", "name"):
        if j.url_slug().lower() == want:
            return j
    raise Http404("City not found")


def _jurisdiction_hub_context(request, jurisdiction: Jurisdiction) -> dict:
    offices = Office.objects.filter(jurisdiction=jurisdiction).order_by("level", "branch", "name")
    current_terms = (
        OfficeholderTerm.objects.select_related("person", "office", "district")
        .filter(jurisdiction=jurisdiction)
        .order_by("-updated_at")[:50]
    )
    elections = Election.objects.filter(jurisdiction=jurisdiction).order_by("-date")[:10]

    races = (
        Race.objects.filter(
            Q(office__jurisdiction=jurisdiction)
            | Q(election__jurisdiction=jurisdiction)
            | Q(district__jurisdiction=jurisdiction)
        )
        .select_related("office", "election", "district")
        .prefetch_related(
            Prefetch(
                "candidacies",
                queryset=Candidacy.objects.select_related("person").order_by(
                    "-is_incumbent", "person__last_name", "person__first_name"
                ),
            )
        )
        .distinct()
        .order_by("-election__date", "office__name")[:_RACE_HUB_LIMIT]
    )

    ct = ContentType.objects.get_for_model(Jurisdiction)
    sources = (
        SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=jurisdiction.id)
        .order_by("-fetched_at")
        .all()
    )

    canonical_url = canonical_jurisdiction_public_url(request, jurisdiction)
    return {
        "jurisdiction": jurisdiction,
        "offices": offices,
        "current_terms": current_terms,
        "elections": elections,
        "races": races,
        "sources": sources,
        "canonical_url": canonical_url,
    }


def counties_root(request):
    return HttpResponseRedirect(reverse("geo:counties_list", kwargs={"state": "TX"}))


def counties_list(request, state: str):
    state_u = _validate_us_state(state)
    qs = Jurisdiction.objects.filter(state=state_u, jurisdiction_type=JurisdictionType.COUNTY).order_by("name")
    counties = dedupe_jurisdictions_queryset_by_url_slug(qs)
    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "geo/counties_list.html",
        {
            "state": state_u,
            "counties": counties,
            "canonical_url": canonical_url,
        },
    )


def county_detail(request, state: str, county_slug: str):
    jurisdiction = resolve_county_jurisdiction(state, county_slug)
    ctx = _jurisdiction_hub_context(request, jurisdiction)
    return render(request, "geo/jurisdiction_detail.html", ctx)


def cities_root(request):
    return HttpResponseRedirect(reverse("geo:cities_list", kwargs={"state": "TX"}))


def cities_list(request, state: str):
    state_u = _validate_us_state(state)
    qs = Jurisdiction.objects.filter(state=state_u, jurisdiction_type__in=_MUNICIPAL_TYPES).order_by("name")
    cities = dedupe_jurisdictions_queryset_by_url_slug(qs)
    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "geo/cities_list.html",
        {
            "state": state_u,
            "cities": cities,
            "canonical_url": canonical_url,
        },
    )


def city_detail(request, state: str, city_slug: str):
    jurisdiction = resolve_city_jurisdiction(state, city_slug)
    ctx = _jurisdiction_hub_context(request, jurisdiction)
    return render(request, "geo/jurisdiction_detail.html", ctx)


def jurisdiction_detail(request, public_id):
    jurisdiction = get_object_or_404(Jurisdiction, public_id=public_id)
    ctx = _jurisdiction_hub_context(request, jurisdiction)
    return render(request, "geo/jurisdiction_detail.html", ctx)


def district_detail(request, public_id):
    district = get_object_or_404(District.objects.select_related("jurisdiction"), public_id=public_id)
    races = (
        Race.objects.select_related("office", "election")
        .filter(district=district)
        .order_by("-election__date")[:25]
    )
    terms = (
        OfficeholderTerm.objects.select_related("person", "office", "jurisdiction")
        .filter(district=district)
        .order_by("-updated_at")[:50]
    )

    ct = ContentType.objects.get_for_model(District)
    sources = (
        SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=district.id)
        .order_by("-fetched_at")
        .all()
    )

    canonical_url = request.build_absolute_uri(request.path)
    return render(
        request,
        "geo/district_detail.html",
        {
            "district": district,
            "races": races,
            "terms": terms,
            "sources": sources,
            "canonical_url": canonical_url,
        },
    )
