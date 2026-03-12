from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render

from apps.elections.models import OfficeholderTerm, Race
from apps.ingestion.models import SourceRecord

from .models import Office


def office_detail(request, public_id):
    office = get_object_or_404(Office.objects.select_related("jurisdiction", "default_district"), public_id=public_id)

    terms = (
        OfficeholderTerm.objects.select_related("person", "district", "jurisdiction")
        .filter(office=office)
        .order_by("-status", "-end_date", "-updated_at")[:50]
    )
    races = Race.objects.select_related("election", "district").filter(office=office).order_by("-election__date")[:25]

    ct = ContentType.objects.get_for_model(Office)
    sources = (
        SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=office.id)
        .order_by("-fetched_at")
        .all()
    )

    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "offices/office_detail.html",
        {"office": office, "terms": terms, "races": races, "sources": sources, "canonical_url": canonical_url},
    )

