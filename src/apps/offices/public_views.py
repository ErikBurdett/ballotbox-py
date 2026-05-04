from __future__ import annotations

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Exists, Max, Min, OuterRef, Q, Subquery
from django.shortcuts import render

from apps.elections.models import OfficeholderTerm, TermStatus
from apps.geo.models import DistrictType, Jurisdiction, JurisdictionType
from apps.media.models import VideoEmbed
from apps.people.models import ContactMethod, ExternalLink, Party, Person, SocialLink

from .models import OfficeBranch, OfficeLevel

GROUNDWATER_BOARD_OFFICE_NAME = "Groundwater Conservation District Board Director"


def _dedupe_terms_for_directory(terms: list) -> list:
    """Collapse duplicate term rows for the same office + jurisdiction + district + status.

    Sync can create multiple ``OfficeholderTerm`` rows that read the same on the card; each has its own
    ``updated_at``. Keep the term with the latest ``updated_at`` per key.
    """
    if len(terms) < 2:
        return terms
    best: dict[tuple, OfficeholderTerm] = {}
    for t in sorted(terms, key=lambda x: x.updated_at, reverse=True):
        key = (t.office_id, t.office.jurisdiction_id, t.district_id, t.status)
        if key not in best:
            best[key] = t
    return sorted(
        best.values(),
        key=lambda x: (-x.updated_at.timestamp(), x.office.name.lower(), x.id),
    )


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


def _apply_global_search_terms(qs, query: str):
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


def officials_directory(request, *, groundwater_only: bool = False):
    q = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip().upper()
    if not state:
        state = str(getattr(settings, "BALLOTPEDIA_SYNC_STATE_CODE", "") or "").strip().upper()
    if not state:
        try:
            state = str((getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}).get("state_code") or "").strip().upper()
        except Exception:
            state = ""
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
    groundwater_only = groundwater_only or _truthy(request.GET.get("groundwater"))

    sort = (request.GET.get("sort") or "updated").strip()

    terms = OfficeholderTerm.objects.select_related("person", "office", "office__jurisdiction", "district", "jurisdiction")

    if q:
        terms = _apply_global_search_terms(terms, q)

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
    if groundwater_only:
        terms = terms.filter(
            office__jurisdiction__state="TX",
            office__jurisdiction__jurisdiction_type=JurisdictionType.SPECIAL_DISTRICT,
            office__name=GROUNDWATER_BOARD_OFFICE_NAME,
        )

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

    # One directory row per person; aggregate for sort keys, then prefetch all matching terms per page.
    person_agg = (
        terms.values("person_id")
        .annotate(
            max_updated=Max("updated_at"),
            min_office_name=Min("office__name"),
            min_jurisdiction_name=Min("office__jurisdiction__name"),
        )
        .annotate(sort_last=Subquery(Person.objects.filter(pk=OuterRef("person_id")).values("last_name")[:1]))
    )
    if sort == "updated":
        person_agg = person_agg.order_by("-max_updated", "person_id")
    elif sort == "name":
        person_agg = person_agg.order_by("sort_last", "person_id")
    elif sort == "office":
        person_agg = person_agg.order_by("min_office_name", "person_id")
    elif sort == "jurisdiction":
        person_agg = person_agg.order_by("min_jurisdiction_name", "person_id")
    else:
        person_agg = person_agg.order_by("-max_updated", "person_id")

    paginator = Paginator(person_agg, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    pids = [row["person_id"] for row in page_obj.object_list]
    by_person: dict[int, list] = {pid: [] for pid in pids}
    if pids:
        for term in (
            terms.filter(person_id__in=pids)
            .select_related("person", "office", "office__jurisdiction", "district", "jurisdiction")
            .order_by("-updated_at", "office__name", "id")
        ):
            by_person[term.person_id].append(term)

    directory_rows = []
    for row in page_obj.object_list:
        pid = row["person_id"]
        raw = by_person.get(pid) or []
        has_video = any(getattr(t, "has_video", False) for t in raw)
        tlist = _dedupe_terms_for_directory(raw)
        person = tlist[0].person if tlist else Person.objects.get(pk=pid)
        directory_rows.append(
            {
                "person": person,
                "terms": tlist,
                "has_video": has_video,
            }
        )

    states = Jurisdiction.objects.values_list("state", flat=True).distinct().order_by("state")

    context = {
        "page_obj": page_obj,
        "directory_rows": directory_rows,
        "states": states,
        "canonical_url": request.build_absolute_uri(),
        "jurisdiction_type_choices": JurisdictionType.choices,
        "district_type_choices": DistrictType.choices,
        "office_level_choices": OfficeLevel.choices,
        "office_branch_choices": OfficeBranch.choices,
        "party_choices": Party.choices,
        "directory_title": "Groundwater Conservation District officials"
        if groundwater_only
        else "Current elected officials",
        "directory_description": (
            "Current board officials tied to Texas Groundwater Conservation District jurisdictions synced from TCEQ."
            if groundwater_only
            else "Filter by geography, office, party, and status. URLs are shareable."
        ),
        "officials_form_url_name": "offices:groundwater_officials_directory"
        if groundwater_only
        else "offices:officials_directory",
        "filters": {
            "q": q,
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
            "groundwater": groundwater_only,
        },
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "offices/partials/_officials_results.html", context)

    return render(request, "offices/officials_directory.html", context)


def groundwater_officials_directory(request):
    return officials_directory(request, groundwater_only=True)

