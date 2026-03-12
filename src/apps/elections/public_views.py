from __future__ import annotations

from datetime import date

from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render

from apps.geo.models import DistrictType, Jurisdiction, JurisdictionType
from apps.media.models import VideoEmbed
from apps.offices.models import OfficeBranch, OfficeLevel
from apps.people.models import Party

from .models import Candidacy, CandidacyStatus


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def candidates_directory(request):
    state = (request.GET.get("state") or "").strip().upper()
    county = (request.GET.get("county") or "").strip()
    city = (request.GET.get("city") or "").strip()
    jurisdiction_type = (request.GET.get("jurisdiction_type") or "").strip()

    district_type = (request.GET.get("district_type") or "").strip()
    district_q = (request.GET.get("district") or "").strip()

    office_level = (request.GET.get("office_level") or "").strip()
    office_branch = (request.GET.get("office_branch") or "").strip()
    party = (request.GET.get("party") or "").strip()

    election_year = (request.GET.get("election_year") or "").strip()
    election_date = (request.GET.get("election_date") or "").strip()

    status = (request.GET.get("status") or "").strip()
    incumbent_only = _truthy(request.GET.get("incumbent"))
    challenger_only = _truthy(request.GET.get("challenger"))
    has_video = _truthy(request.GET.get("has_video"))

    sort = (request.GET.get("sort") or "election_date").strip()

    candidacies = Candidacy.objects.select_related(
        "person",
        "race__office",
        "race__district",
        "race__election",
        "race__election__jurisdiction",
    )

    if status in {c[0] for c in CandidacyStatus.choices}:
        candidacies = candidacies.filter(status=status)

    if incumbent_only:
        candidacies = candidacies.filter(is_incumbent=True)
    if challenger_only:
        candidacies = candidacies.filter(is_challenger=True)

    if state:
        candidacies = candidacies.filter(race__election__jurisdiction__state=state)
    if county:
        candidacies = candidacies.filter(race__election__jurisdiction__county__iexact=county)
    if city:
        candidacies = candidacies.filter(race__election__jurisdiction__city__iexact=city)
    if jurisdiction_type in {c[0] for c in JurisdictionType.choices}:
        candidacies = candidacies.filter(race__election__jurisdiction__jurisdiction_type=jurisdiction_type)

    if district_type in {c[0] for c in DistrictType.choices}:
        candidacies = candidacies.filter(race__district__district_type=district_type)
    if district_q:
        candidacies = candidacies.filter(
            Q(race__district__name__icontains=district_q) | Q(race__district__number__icontains=district_q)
        )

    if office_level in {c[0] for c in OfficeLevel.choices}:
        candidacies = candidacies.filter(race__office__level=office_level)
    if office_branch in {c[0] for c in OfficeBranch.choices}:
        candidacies = candidacies.filter(race__office__branch=office_branch)
    if party in {c[0] for c in Party.choices}:
        candidacies = candidacies.filter(party=party)

    if election_year.isdigit():
        candidacies = candidacies.filter(race__election__date__year=int(election_year))

    if election_date:
        try:
            y, m, d = [int(x) for x in election_date.split("-")]
            candidacies = candidacies.filter(race__election__date=date(y, m, d))
        except Exception:
            pass

    person_video = VideoEmbed.objects.filter(is_approved=True, person_id=OuterRef("person_id"))
    candidacy_video = VideoEmbed.objects.filter(is_approved=True, candidacy_id=OuterRef("pk"))
    candidacies = candidacies.annotate(has_video=Exists(person_video) | Exists(candidacy_video))
    if has_video:
        candidacies = candidacies.filter(has_video=True)

    sort_map = {
        "election_date": "-race__election__date",
        "updated": "-updated_at",
        "name": "person__last_name",
        "office": "race__office__name",
    }
    candidacies = candidacies.order_by(sort_map.get(sort, "-race__election__date"), "id")

    paginator = Paginator(candidacies, 20)
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
        "candidacy_status_choices": CandidacyStatus.choices,
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
            "election_year": election_year,
            "election_date": election_date,
            "status": status,
            "incumbent": incumbent_only,
            "challenger": challenger_only,
            "has_video": has_video,
            "sort": sort,
        },
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "elections/partials/_candidates_results.html", context)

    return render(request, "elections/candidates_directory.html", context)

