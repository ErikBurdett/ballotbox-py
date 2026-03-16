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
from apps.people.models import ContactMethod, ExternalLink, Party, SocialLink


def health(request):
    return JsonResponse({"ok": True})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _norm_spaces(value: str) -> str:
    v = (value or "").replace("_", " ").replace("-", " ")
    return " ".join(v.strip().split())


def _norm_county(value: str) -> str:
    v = _norm_spaces(value)
    if v.lower().endswith(" county"):
        v = v[:-7].strip()
    return v


def _match_choice_values(query: str, choices) -> set[str]:
    q = (query or "").strip().lower()
    if not q:
        return set()
    matches: set[str] = set()
    for value, label in choices:
        v = str(value).lower()
        l = str(label).strip().lower()
        if q == v or q == l:
            matches.add(str(value))
    return matches


def _apply_global_search_candidates(qs, query: str):
    q = _norm_spaces(query)
    if not q:
        return qs
    q_lower = q.lower()
    q_state = q.upper() if len(q) == 2 and q.isalpha() else ""
    q_county = _norm_county(q)

    person_contact = ContactMethod.objects.filter(person_id=OuterRef("person_id"), is_public=True).filter(
        Q(value__icontains=q) | Q(label__icontains=q)
    )
    person_external = ExternalLink.objects.filter(person_id=OuterRef("person_id")).filter(
        Q(url__icontains=q) | Q(label__icontains=q)
    )
    person_social = SocialLink.objects.filter(person_id=OuterRef("person_id")).filter(
        Q(url__icontains=q) | Q(handle__icontains=q)
    )

    qs = qs.annotate(
        q_contact=Exists(person_contact),
        q_external=Exists(person_external),
        q_social=Exists(person_social),
    )

    office_level_matches = _match_choice_values(q, OfficeLevel.choices)
    office_branch_matches = _match_choice_values(q, OfficeBranch.choices)
    jurisdiction_type_matches = _match_choice_values(q, JurisdictionType.choices)
    district_type_matches = _match_choice_values(q, DistrictType.choices)
    party_matches = _match_choice_values(q, Party.choices)
    candidacy_status_matches = _match_choice_values(q, CandidacyStatus.choices)

    search_q = (
        Q(person__first_name__icontains=q)
        | Q(person__last_name__icontains=q)
        | Q(person__preferred_name__icontains=q)
        | Q(person__manual_display_name__icontains=q)
        | Q(person__manual_party__icontains=q)
        | Q(race__office__name__icontains=q)
        | Q(race__office__level__in=office_level_matches)  # type: ignore[arg-type]
        | Q(race__office__branch__in=office_branch_matches)  # type: ignore[arg-type]
        | Q(race__office__jurisdiction__name__icontains=q)
        | Q(race__office__jurisdiction__county__icontains=q_county)
        | Q(race__office__jurisdiction__city__icontains=q)
        | Q(race__office__jurisdiction__jurisdiction_type__in=jurisdiction_type_matches)  # type: ignore[arg-type]
        | Q(race__district__name__icontains=q)
        | Q(race__district__number__icontains=q)
        | Q(race__district__district_type__in=district_type_matches)  # type: ignore[arg-type]
        | Q(race__election__name__icontains=q)
        | Q(race__contest_type__icontains=q)
        | Q(race__title__icontains=q)
        | Q(race__about_office__icontains=q)
        | Q(race__body__icontains=q)
        | Q(party__in=party_matches)  # type: ignore[arg-type]
        | Q(status__in=candidacy_status_matches)  # type: ignore[arg-type]
        | Q(running_mate_full_name__icontains=q)
        | Q(running_mate_title__icontains=q)
        | Q(q_contact=True)
        | Q(q_external=True)
        | Q(q_social=True)
    )

    if q_state:
        search_q = search_q | Q(race__office__jurisdiction__state=q_state) | Q(race__election__jurisdiction__state=q_state)

    if q_lower in {"incumbent"}:
        search_q = search_q | Q(is_incumbent=True)
    if q_lower in {"challenger"}:
        search_q = search_q | Q(is_challenger=True)
    if q_lower in {"write-in", "writein", "write in"}:
        search_q = search_q | Q(is_write_in=True)

    if q.isdigit() and len(q) == 4:
        search_q = search_q | Q(race__election__date__year=int(q))
    if "-" in q and len(q) == 10:
        try:
            y, m, d = [int(x) for x in q.split("-")]
            search_q = search_q | Q(race__election__date=date(y, m, d))
        except Exception:
            pass

    return qs.filter(search_q)


def _apply_global_search_officials(qs, query: str):
    q = _norm_spaces(query)
    if not q:
        return qs
    q_lower = q.lower()
    q_state = q.upper() if len(q) == 2 and q.isalpha() else ""
    q_county = _norm_county(q)

    person_contact = ContactMethod.objects.filter(person_id=OuterRef("person_id"), is_public=True).filter(
        Q(value__icontains=q) | Q(label__icontains=q)
    )
    person_external = ExternalLink.objects.filter(person_id=OuterRef("person_id")).filter(
        Q(url__icontains=q) | Q(label__icontains=q)
    )
    person_social = SocialLink.objects.filter(person_id=OuterRef("person_id")).filter(
        Q(url__icontains=q) | Q(handle__icontains=q)
    )

    qs = qs.annotate(
        q_contact=Exists(person_contact),
        q_external=Exists(person_external),
        q_social=Exists(person_social),
    )

    office_level_matches = _match_choice_values(q, OfficeLevel.choices)
    office_branch_matches = _match_choice_values(q, OfficeBranch.choices)
    jurisdiction_type_matches = _match_choice_values(q, JurisdictionType.choices)
    district_type_matches = _match_choice_values(q, DistrictType.choices)
    party_matches = _match_choice_values(q, Party.choices)
    term_status_matches = _match_choice_values(q, TermStatus.choices)

    search_q = (
        Q(person__first_name__icontains=q)
        | Q(person__last_name__icontains=q)
        | Q(person__preferred_name__icontains=q)
        | Q(person__manual_display_name__icontains=q)
        | Q(person__manual_party__icontains=q)
        | Q(office__name__icontains=q)
        | Q(office__level__in=office_level_matches)  # type: ignore[arg-type]
        | Q(office__branch__in=office_branch_matches)  # type: ignore[arg-type]
        | Q(office__jurisdiction__name__icontains=q)
        | Q(office__jurisdiction__county__icontains=q_county)
        | Q(office__jurisdiction__city__icontains=q)
        | Q(office__jurisdiction__jurisdiction_type__in=jurisdiction_type_matches)  # type: ignore[arg-type]
        | Q(district__name__icontains=q)
        | Q(district__number__icontains=q)
        | Q(district__district_type__in=district_type_matches)  # type: ignore[arg-type]
        | Q(party__in=party_matches)  # type: ignore[arg-type]
        | Q(status__in=term_status_matches)  # type: ignore[arg-type]
        | Q(review_notes__icontains=q)
        | Q(q_contact=True)
        | Q(q_external=True)
        | Q(q_social=True)
    )

    if q_state:
        search_q = search_q | Q(office__jurisdiction__state=q_state) | Q(jurisdiction__state=q_state)

    if q_lower in {"incumbent"}:
        search_q = search_q | Q(status=TermStatus.CURRENT)

    return qs.filter(search_q)


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
    q = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip().upper()
    county = _norm_county(request.GET.get("county") or "")
    city = _norm_spaces(request.GET.get("city") or "")
    jurisdiction_type = (request.GET.get("jurisdiction_type") or "").strip()
    district_type = (request.GET.get("district_type") or "").strip()
    district_q = (request.GET.get("district") or "").strip()
    office_level = (request.GET.get("office_level") or "").strip()
    office_branch = (request.GET.get("office_branch") or "").strip()
    party = (request.GET.get("party") or "").strip()
    status = (request.GET.get("status") or "current").strip()
    has_video = _truthy(request.GET.get("has_video"))
    sort = (request.GET.get("sort") or "updated").strip()

    terms = OfficeholderTerm.objects.select_related("person", "office", "office__jurisdiction", "district", "jurisdiction")
    if q:
        terms = _apply_global_search_officials(terms, q)
    if status == "current":
        terms = terms.filter(status__in=[TermStatus.CURRENT, TermStatus.UNKNOWN], end_date__isnull=True)
    elif status == "former":
        terms = terms.filter(status=TermStatus.FORMER)

    if state:
        terms = terms.filter(Q(jurisdiction__state=state) | Q(office__jurisdiction__state=state))
    if county:
        terms = terms.filter(
            Q(jurisdiction__county__iexact=county)
            | Q(office__jurisdiction__county__iexact=county)
            | Q(office__jurisdiction__county__icontains=county)
            | Q(office__jurisdiction__jurisdiction_type=JurisdictionType.COUNTY, office__jurisdiction__name__icontains=county)
        )
    if city:
        city_like = {
            JurisdictionType.CITY,
            JurisdictionType.TOWN,
            JurisdictionType.TOWNSHIP,
            JurisdictionType.VILLAGE,
            JurisdictionType.BOROUGH,
        }
        terms = terms.filter(
            Q(jurisdiction__city__iexact=city)
            | Q(office__jurisdiction__city__iexact=city)
            | Q(office__jurisdiction__city__icontains=city)
            | Q(office__jurisdiction__jurisdiction_type__in=city_like, office__jurisdiction__name__icontains=city)
        )
    if jurisdiction_type in {c[0] for c in JurisdictionType.choices}:
        terms = terms.filter(Q(jurisdiction__jurisdiction_type=jurisdiction_type) | Q(office__jurisdiction__jurisdiction_type=jurisdiction_type))

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
            "jurisdiction": {"public_id": str(t.office.jurisdiction.public_id), "name": t.office.jurisdiction.name, "state": t.office.jurisdiction.state, "jurisdiction_type": t.office.jurisdiction.jurisdiction_type, "county": t.office.jurisdiction.county, "city": t.office.jurisdiction.city},
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
    q = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip().upper()
    county = _norm_county(request.GET.get("county") or "")
    city = _norm_spaces(request.GET.get("city") or "")
    jurisdiction_type = (request.GET.get("jurisdiction_type") or "").strip()
    district_type = (request.GET.get("district_type") or "").strip()
    district_q = (request.GET.get("district") or "").strip()
    office_level = (request.GET.get("office_level") or "").strip()
    office_branch = (request.GET.get("office_branch") or "").strip()
    party = (request.GET.get("party") or "").strip()
    election_year = (request.GET.get("election_year") or "").strip()
    if not election_year:
        election_year = str(date.today().year)
    election_date = (request.GET.get("election_date") or "").strip()
    status = (request.GET.get("status") or "").strip()
    incumbent_only = _truthy(request.GET.get("incumbent"))
    challenger_only = _truthy(request.GET.get("challenger"))
    has_video = _truthy(request.GET.get("has_video"))
    sort = (request.GET.get("sort") or "election_date").strip()

    candidacies = Candidacy.objects.select_related(
        "person",
        "race__office",
        "race__office__jurisdiction",
        "race__district",
        "race__election",
        "race__election__jurisdiction",
    )
    if q:
        candidacies = _apply_global_search_candidates(candidacies, q)

    if status in {c[0] for c in CandidacyStatus.choices}:
        candidacies = candidacies.filter(status=status)
    if incumbent_only:
        candidacies = candidacies.filter(is_incumbent=True)
    if challenger_only:
        candidacies = candidacies.filter(is_challenger=True)

    if state:
        candidacies = candidacies.filter(race__office__jurisdiction__state=state)
    if county:
        candidacies = candidacies.filter(
            Q(race__office__jurisdiction__county__iexact=county)
            | Q(race__office__jurisdiction__county__icontains=county)
            | Q(
                race__office__jurisdiction__jurisdiction_type=JurisdictionType.COUNTY,
                race__office__jurisdiction__name__icontains=county,
            )
        )
    if city:
        city_like = {
            JurisdictionType.CITY,
            JurisdictionType.TOWN,
            JurisdictionType.TOWNSHIP,
            JurisdictionType.VILLAGE,
            JurisdictionType.BOROUGH,
        }
        candidacies = candidacies.filter(
            Q(race__office__jurisdiction__city__iexact=city)
            | Q(race__office__jurisdiction__city__icontains=city)
            | Q(
                race__office__jurisdiction__jurisdiction_type__in=city_like,
                race__office__jurisdiction__name__icontains=city,
            )
        )
    if jurisdiction_type in {c[0] for c in JurisdictionType.choices}:
        candidacies = candidacies.filter(race__office__jurisdiction__jurisdiction_type=jurisdiction_type)

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
            "jurisdiction": {"public_id": str(c.race.office.jurisdiction.public_id), "name": c.race.office.jurisdiction.name, "state": c.race.office.jurisdiction.state, "jurisdiction_type": c.race.office.jurisdiction.jurisdiction_type, "county": c.race.office.jurisdiction.county, "city": c.race.office.jurisdiction.city},
            "district": {"public_id": str(c.race.district.public_id), "label": str(c.race.district), "district_type": c.race.district.district_type} if c.race.district_id else None,
            "election": {"public_id": str(c.race.election.public_id), "name": c.race.election.name, "date": c.race.election.date.isoformat(), "election_type": c.race.election.election_type},
            "status": c.status,
            "is_incumbent": c.is_incumbent,
            "is_challenger": c.is_challenger,
            "is_write_in": c.is_write_in,
            "endorsement_count": c.endorsement_count,
            "running_mate_full_name": c.running_mate_full_name,
            "running_mate_title": c.running_mate_title,
            "ranked_choice_voting_round": c.ranked_choice_voting_round,
            "race_meta": {
                "contest_type": c.race.contest_type,
                "seats_up_for_election": c.race.seats_up_for_election,
                "ranked_choice": c.race.ranked_choice,
                "ranked_choice_rank_number": c.race.ranked_choice_rank_number,
                "has_primary": c.race.has_primary,
                "primary_date": c.race.primary_date.isoformat() if c.race.primary_date else None,
                "general_date": c.race.general_date.isoformat() if c.race.general_date else None,
                "title": c.race.title,
            },
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

