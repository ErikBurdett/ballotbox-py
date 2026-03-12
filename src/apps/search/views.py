from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.contrib.postgres.search import TrigramSimilarity
from django.shortcuts import render
from django_ratelimit.decorators import ratelimit

from apps.geo.models import District, Jurisdiction
from apps.offices.models import Office
from apps.people.models import Person


@ratelimit(key="ip", rate="60/m", block=True)
def global_search(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) > 120:
        q = q[:120]

    people = []
    offices = []
    districts = []
    jurisdictions = []

    if q:
        query = SearchQuery(q, search_type="websearch", config="english")

        people_vector = (
            SearchVector("preferred_name", weight="A")
            + SearchVector("first_name", weight="B")
            + SearchVector("last_name", weight="A")
        )
        people = (
            Person.objects.annotate(
                rank=SearchRank(people_vector, query),
                sim=TrigramSimilarity("last_name", q) + TrigramSimilarity("first_name", q),
            )
            .filter(rank__gt=0.05)
            .order_by("-rank", "-sim", "last_name")[:15]
        )

        office_vector = SearchVector("name", weight="A") + SearchVector("description", weight="B")
        offices = (
            Office.objects.annotate(rank=SearchRank(office_vector, query), sim=TrigramSimilarity("name", q))
            .filter(rank__gt=0.05)
            .order_by("-rank", "-sim", "name")[:15]
        )

        district_vector = SearchVector("name", weight="A") + SearchVector("number", weight="A")
        districts = (
            District.objects.select_related("jurisdiction")
            .annotate(rank=SearchRank(district_vector, query), sim=TrigramSimilarity("name", q))
            .filter(rank__gt=0.05)
            .order_by("-rank", "-sim", "name")[:15]
        )

        jurisdiction_vector = (
            SearchVector("name", weight="A")
            + SearchVector("county", weight="B")
            + SearchVector("city", weight="B")
            + SearchVector("state", weight="C")
        )
        jurisdictions = (
            Jurisdiction.objects.annotate(rank=SearchRank(jurisdiction_vector, query), sim=TrigramSimilarity("name", q))
            .filter(rank__gt=0.05)
            .order_by("-rank", "-sim", "name")[:15]
        )

    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "search/global_search.html",
        {
            "q": q,
            "people": people,
            "offices": offices,
            "districts": districts,
            "jurisdictions": jurisdictions,
            "canonical_url": canonical_url,
        },
    )

