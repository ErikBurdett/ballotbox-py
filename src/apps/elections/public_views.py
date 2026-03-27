from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Exists, Max, Min, OuterRef, Q, Subquery
from django.shortcuts import render

from apps.geo.models import DistrictType, Jurisdiction, JurisdictionType
from apps.media.models import VideoEmbed
from apps.offices.models import OfficeBranch, OfficeLevel
from apps.people.models import ContactMethod, ExternalLink, Party, Person, SocialLink

from .models import Candidacy, CandidacyStatus


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


def _apply_global_search_candidacies(qs, query: str):
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


def candidates_directory(request):
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
        candidacies = _apply_global_search_candidacies(candidacies, q)

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

    # One directory row per person; aggregate for sort keys, then prefetch all matching candidacies per page.
    person_agg = (
        candidacies.values("person_id")
        .annotate(
            max_election_date=Max("race__election__date"),
            max_updated=Max("updated_at"),
            min_office_name=Min("race__office__name"),
        )
        .annotate(sort_last=Subquery(Person.objects.filter(pk=OuterRef("person_id")).values("last_name")[:1]))
    )
    if sort == "election_date":
        person_agg = person_agg.order_by("-max_election_date", "person_id")
    elif sort == "updated":
        person_agg = person_agg.order_by("-max_updated", "person_id")
    elif sort == "name":
        person_agg = person_agg.order_by("sort_last", "person_id")
    elif sort == "office":
        person_agg = person_agg.order_by("min_office_name", "person_id")
    else:
        person_agg = person_agg.order_by("-max_election_date", "person_id")

    paginator = Paginator(person_agg, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    pids = [row["person_id"] for row in page_obj.object_list]
    by_person: dict[int, list] = {pid: [] for pid in pids}
    if pids:
        for cand in (
            candidacies.filter(person_id__in=pids)
            .select_related(
                "person",
                "race__office",
                "race__office__jurisdiction",
                "race__district",
                "race__election",
                "race__election__jurisdiction",
            )
            .order_by("-race__election__date", "race__office__name", "id")
        ):
            by_person[cand.person_id].append(cand)

    directory_rows = []
    for row in page_obj.object_list:
        pid = row["person_id"]
        clist = by_person.get(pid) or []
        person = clist[0].person if clist else Person.objects.get(pk=pid)
        directory_rows.append(
            {
                "person": person,
                "candidacies": clist,
                "has_video": any(getattr(c, "has_video", False) for c in clist),
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
        "candidacy_status_choices": CandidacyStatus.choices,
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

