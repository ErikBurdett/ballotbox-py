from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from apps.elections.models import Candidacy, CandidacyStatus, OfficeholderTerm, TermStatus
from apps.ingestion.models import SourceRecord
from apps.media.models import VideoEmbed

from .models import ContactType, ExternalLinkKind, Person


def person_detail(request, public_id):
    person = get_object_or_404(
        Person.objects.prefetch_related(
            "contact_methods",
            "social_links",
            "external_links",
            Prefetch(
                "officeholder_terms",
                queryset=OfficeholderTerm.objects.select_related("office", "district", "jurisdiction").order_by(
                    "-start_date", "-updated_at"
                ),
            ),
            Prefetch(
                "candidacies",
                queryset=Candidacy.objects.select_related("race__office", "race__district", "race__election").order_by(
                    "-race__election__date", "-updated_at"
                ),
            ),
            Prefetch(
                "videos",
                queryset=VideoEmbed.objects.filter(is_approved=True).order_by("-published_at", "-updated_at"),
            ),
        ),
        public_id=public_id,
    )

    current_terms = [t for t in person.officeholder_terms.all() if t.is_current]
    running_candidacies = [
        c
        for c in person.candidacies.all()
        if c.status in {CandidacyStatus.DECLARED, CandidacyStatus.RUNNING, CandidacyStatus.UNKNOWN}
    ]

    ballotpedia = next(
        (l for l in person.external_links.all() if l.kind == ExternalLinkKind.BALLOTPEDIA), None
    )
    email = next((c for c in person.contact_methods.all() if c.contact_type == ContactType.EMAIL), None)
    phone = next((c for c in person.contact_methods.all() if c.contact_type == ContactType.PHONE), None)
    website = next((c for c in person.contact_methods.all() if c.contact_type == ContactType.WEBSITE), None)

    ct = ContentType.objects.get_for_model(Person)
    sources = (
        SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=person.id)
        .order_by("-fetched_at")
        .all()
    )

    canonical_url = request.build_absolute_uri()

    return render(
        request,
        "people/person_detail.html",
        {
            "person": person,
            "current_terms": current_terms,
            "running_candidacies": running_candidacies,
            "ballotpedia": ballotpedia,
            "email": email,
            "phone": phone,
            "website": website,
            "sources": sources,
            "canonical_url": canonical_url,
        },
    )

