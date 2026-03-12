from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django_ratelimit.decorators import ratelimit

from apps.elections.models import Candidacy, CandidacyStatus, OfficeholderTerm, TermStatus
from apps.geo.models import DistrictType, Jurisdiction, JurisdictionType
from apps.media.models import VideoEmbed
from apps.offices.models import OfficeBranch, OfficeLevel
from apps.people.models import Party


def health(request):
    return JsonResponse({"ok": True})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _page_params(request):
    try:
        page = int(request.GET.get("page") or 1)
    except Exception:
        page = 1
    try:
        page_size = int(request.GET.get("page_size") or 20)
    except Exception:
        page_size = 20
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    return page, page_size


def _pagination_links(request, page_obj):
    def url_for_page(n: int | None):
        if not n:
            return None
        params = request.GET.copy()
        params["page"] = str(n)
        return request.build_absolute_uri(request.path + "?" + urlencode(params, doseq=True))

    return {"next": url_for_page(page_obj.next_page_number() if page_obj.has_next() else None),
            "previous": url_for_page(page_obj.previous_page_number() if page_obj.has_previous() else None)}


@require_GET
@ratelimit(key="ip", rate="60/m", block=True)
def officials(request):
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

    page, page_size = _page_params(request)
    paginator = Paginator(terms, page_size)
    page_obj = paginator.get_page(page)

    results = [
        {
            "person": {"public_id": str(t.person.public_id), "name": t.person.display_name, "party": t.display_party},
            "office": {"public_id": str(t.office.public_id), "name": t.office.name, "level": t.office.level, "branch": t.office.branch},
            "jurisdiction": {"public_id": str(t.jurisdiction.public_id), "name": t.jurisdiction.name, "state": t.jurisdiction.state, "jurisdiction_type": t.jurisdiction.jurisdiction_type},
            "district": {"public_id": str(t.district.public_id), "label": str(t.district), "district_type": t.district.district_type} if t.district_id else None,
            "status": t.status,
            "has_video": bool(getattr(t, "has_video", False)),
            "updated_at": t.updated_at.isoformat(),
            "last_verified_at": t.last_verified_at.isoformat() if t.last_verified_at else None,
        }
        for t in page_obj.object_list
    ]

    links = _pagination_links(request, page_obj)
    return JsonResponse({"count": paginator.count, "next": links["next"], "previous": links["previous"], "results": results})


@require_GET
@ratelimit(key="ip", rate="60/m", block=True)
def candidates(request):
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

    page, page_size = _page_params(request)
    paginator = Paginator(candidacies, page_size)
    page_obj = paginator.get_page(page)

    results = [
        {
            "person": {"public_id": str(c.person.public_id), "name": c.person.display_name, "party": c.display_party},
            "office": {"public_id": str(c.race.office.public_id), "name": c.race.office.name, "level": c.race.office.level, "branch": c.race.office.branch},
            "jurisdiction": {"public_id": str(c.race.election.jurisdiction.public_id), "name": c.race.election.jurisdiction.name, "state": c.race.election.jurisdiction.state, "jurisdiction_type": c.race.election.jurisdiction.jurisdiction_type},
            "district": {"public_id": str(c.race.district.public_id), "label": str(c.race.district), "district_type": c.race.district.district_type} if c.race.district_id else None,
            "election": {"public_id": str(c.race.election.public_id), "name": c.race.election.name, "date": c.race.election.date.isoformat(), "election_type": c.race.election.election_type},
            "status": c.status,
            "is_incumbent": c.is_incumbent,
            "is_challenger": c.is_challenger,
            "has_video": bool(getattr(c, "has_video", False)),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in page_obj.object_list
    ]

    links = _pagination_links(request, page_obj)
    return JsonResponse({"count": paginator.count, "next": links["next"], "previous": links["previous"], "results": results})


@require_GET
@ratelimit(key="ip", rate="120/m", block=True)
def filters(request):
    states = list(Jurisdiction.objects.values_list("state", flat=True).distinct().order_by("state"))
    return JsonResponse(
        {
            "states": states,
            "jurisdiction_types": [{"value": v, "label": l} for v, l in JurisdictionType.choices],
            "district_types": [{"value": v, "label": l} for v, l in DistrictType.choices],
            "office_levels": [{"value": v, "label": l} for v, l in OfficeLevel.choices],
            "office_branches": [{"value": v, "label": l} for v, l in OfficeBranch.choices],
            "parties": [{"value": v, "label": l} for v, l in Party.choices],
            "candidacy_statuses": [{"value": v, "label": l} for v, l in CandidacyStatus.choices],
        }
    )

