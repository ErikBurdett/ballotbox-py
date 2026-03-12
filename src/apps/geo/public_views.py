from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render

from apps.elections.models import Election, OfficeholderTerm, Race
from apps.ingestion.models import SourceRecord
from apps.offices.models import Office

from .models import District, Jurisdiction


def jurisdiction_detail(request, public_id):
    jurisdiction = get_object_or_404(Jurisdiction, public_id=public_id)

    offices = Office.objects.filter(jurisdiction=jurisdiction).order_by("level", "branch", "name")
    current_terms = (
        OfficeholderTerm.objects.select_related("person", "office", "district")
        .filter(jurisdiction=jurisdiction)
        .order_by("-updated_at")[:50]
    )
    elections = Election.objects.filter(jurisdiction=jurisdiction).order_by("-date")[:10]

    ct = ContentType.objects.get_for_model(Jurisdiction)
    sources = (
        SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=jurisdiction.id)
        .order_by("-fetched_at")
        .all()
    )

    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "geo/jurisdiction_detail.html",
        {
            "jurisdiction": jurisdiction,
            "offices": offices,
            "current_terms": current_terms,
            "elections": elections,
            "sources": sources,
            "canonical_url": canonical_url,
        },
    )


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

    canonical_url = request.build_absolute_uri()
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

