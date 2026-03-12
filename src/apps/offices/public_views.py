from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render

from apps.elections.models import OfficeholderTerm, TermStatus
from apps.geo.models import DistrictType, Jurisdiction, JurisdictionType
from apps.media.models import VideoEmbed
from apps.people.models import Party

from .models import OfficeBranch, OfficeLevel


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def officials_directory(request):
    state = (request.GET.get("state") or "").strip().upper()
    county = (request.GET.get("county") or "").strip()
    city = (request.GET.get("city") or "").strip()
    jurisdiction_type = (request.GET.get("jurisdiction_type") or "").strip()

    district_type = (request.GET.get("district_type") or "").strip()
    district_q = (request.GET.get("district") or "").strip()

    office_level = (request.GET.get("office_level") or "").strip()
    office_branch = (request.GET.get("office_branch") or "").strip()
    party = (request.GET.get("party") or "").strip()

    status = (request.GET.get("status") or "current").strip()
    has_video = _truthy(request.GET.get("has_video"))

    sort = (request.GET.get("sort") or "updated").strip()

    terms = OfficeholderTerm.objects.select_related("person", "office", "district", "jurisdiction")

    if status == "current":
        terms = terms.filter(status__in=[TermStatus.CURRENT, TermStatus.UNKNOWN], end_date__isnull=True)
    elif status == "former":
        terms = terms.filter(status=TermStatus.FORMER)

    if state:
        terms = terms.filter(jurisdiction__state=state)
    if county:
        terms = terms.filter(jurisdiction__county__iexact=county)
    if city:
        terms = terms.filter(jurisdiction__city__iexact=city)
    if jurisdiction_type in {c[0] for c in JurisdictionType.choices}:
        terms = terms.filter(jurisdiction__jurisdiction_type=jurisdiction_type)

    if district_type in {c[0] for c in DistrictType.choices}:
        terms = terms.filter(district__district_type=district_type)
    if district_q:
        terms = terms.filter(Q(district__name__icontains=district_q) | Q(district__number__icontains=district_q))

    if office_level in {c[0] for c in OfficeLevel.choices}:
        terms = terms.filter(office__level=office_level)
    if office_branch in {c[0] for c in OfficeBranch.choices}:
        terms = terms.filter(office__branch=office_branch)
    if party in {c[0] for c in Party.choices}:
        terms = terms.filter(party=party)

    video_qs = VideoEmbed.objects.filter(is_approved=True, person_id=OuterRef("person_id"))
    terms = terms.annotate(has_video=Exists(video_qs))
    if has_video:
        terms = terms.filter(has_video=True)

    sort_map = {
        "updated": "-updated_at",
        "name": "person__last_name",
        "office": "office__name",
        "jurisdiction": "jurisdiction__name",
    }
    terms = terms.order_by(sort_map.get(sort, "-updated_at"), "id")

    paginator = Paginator(terms, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    states = Jurisdiction.objects.values_list("state", flat=True).distinct().order_by("state")

    context = {
        "page_obj": page_obj,
        "states": states,
        "canonical_url": request.build_absolute_uri(),
        "jurisdiction_type_choices": JurisdictionType.choices,
        "district_type_choices": DistrictType.choices,
        "office_level_choices": OfficeLevel.choices,
        "office_branch_choices": OfficeBranch.choices,
        "party_choices": Party.choices,
        "filters": {
            "state": state,
            "county": county,
            "city": city,
            "jurisdiction_type": jurisdiction_type,
            "district_type": district_type,
            "district": district_q,
            "office_level": office_level,
            "office_branch": office_branch,
            "party": party,
            "status": status,
            "has_video": has_video,
            "sort": sort,
        },
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "offices/partials/_officials_results.html", context)

    return render(request, "offices/officials_directory.html", context)

