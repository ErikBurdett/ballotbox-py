"""Staff-only CSV downloads from the Django admin index."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Iterable

from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, StreamingHttpResponse

from apps.elections.models import Candidacy, OfficeholderTerm, Race
from apps.people.models import ContactMethod, ContactType, Person
from apps.submissions.models import ProfileSubmission

ExportRow = list[Any]
RowGenerator = Iterable[ExportRow]


def _sanitize_cell(value: Any) -> Any:
    if value is None:
        return ""
    return value


def _csv_response(filename_stem: str, header: list[str], rows: RowGenerator) -> StreamingHttpResponse:
    class _Buffer:
        def write(self, value: str) -> str:
            return value

    writer = csv.writer(_Buffer(), lineterminator="\n")

    def _gen() -> Iterable[bytes]:
        yield writer.writerow(header).encode("utf-8")
        for row in rows:
            yield writer.writerow([_sanitize_cell(c) for c in row]).encode("utf-8")

    response = StreamingHttpResponse(_gen(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename_stem}-{date.today().isoformat()}.csv"'
    return response


def _iter_officials() -> tuple[list[str], RowGenerator]:
    header = [
        "public_id",
        "person_public_id",
        "person_display_name",
        "office_public_id",
        "office_name",
        "jurisdiction_public_id",
        "jurisdiction",
        "district_public_id",
        "district",
        "party",
        "party_other",
        "status",
        "start_date",
        "end_date",
        "review_status",
        "last_verified_at",
        "created_at",
        "updated_at",
    ]

    def rows() -> RowGenerator:
        qs = (
            OfficeholderTerm.objects.select_related("person", "office", "jurisdiction", "district")
            .order_by("id")
            .iterator(chunk_size=500)
        )
        for t in qs:
            yield [
                t.public_id,
                t.person.public_id,
                t.person.display_name,
                t.office.public_id,
                t.office.name,
                t.jurisdiction.public_id,
                str(t.jurisdiction),
                t.district.public_id if t.district_id else "",
                str(t.district) if t.district_id else "",
                t.party,
                t.party_other,
                t.status,
                t.start_date,
                t.end_date,
                t.review_status,
                t.last_verified_at,
                t.created_at,
                t.updated_at,
            ]

    return header, rows()


def _iter_candidacies() -> tuple[list[str], RowGenerator]:
    header = [
        "public_id",
        "person_public_id",
        "person_display_name",
        "race_public_id",
        "election_name",
        "election_date",
        "election_jurisdiction",
        "office_name",
        "district",
        "seat_name",
        "party",
        "party_other",
        "status",
        "is_incumbent",
        "is_challenger",
        "is_write_in",
        "review_status",
        "last_verified_at",
        "created_at",
        "updated_at",
    ]

    def rows() -> RowGenerator:
        qs = (
            Candidacy.objects.select_related(
                "person",
                "race",
                "race__election",
                "race__election__jurisdiction",
                "race__office",
                "race__district",
            )
            .order_by("id")
            .iterator(chunk_size=500)
        )
        for c in qs:
            race = c.race
            ejurisdiction = race.election.jurisdiction
            yield [
                c.public_id,
                c.person.public_id,
                c.person.display_name,
                race.public_id,
                race.election.name,
                race.election.date,
                str(ejurisdiction),
                race.office.name,
                str(race.district) if race.district_id else "",
                race.seat_name,
                c.party,
                c.party_other,
                c.status,
                c.is_incumbent,
                c.is_challenger,
                c.is_write_in,
                c.review_status,
                c.last_verified_at,
                c.created_at,
                c.updated_at,
            ]

    return header, rows()


def _iter_persons() -> tuple[list[str], RowGenerator]:
    header = [
        "public_id",
        "first_name",
        "middle_name",
        "last_name",
        "suffix",
        "preferred_name",
        "display_name",
        "party",
        "party_other",
        "manual_display_name",
        "manual_party",
        "photo_url",
        "manual_photo_url",
        "review_status",
        "last_verified_at",
        "review_notes",
        "created_at",
        "updated_at",
    ]

    def rows() -> RowGenerator:
        for p in Person.objects.order_by("id").iterator(chunk_size=500):
            yield [
                p.public_id,
                p.first_name,
                p.middle_name,
                p.last_name,
                p.suffix,
                p.preferred_name,
                p.display_name,
                p.party,
                p.party_other,
                p.manual_display_name,
                p.manual_party,
                p.photo_url,
                p.manual_photo_url,
                p.review_status,
                p.last_verified_at,
                p.review_notes,
                p.created_at,
                p.updated_at,
            ]

    return header, rows()


def _iter_races() -> tuple[list[str], RowGenerator]:
    header = [
        "public_id",
        "election_public_id",
        "election_name",
        "election_date",
        "election_type",
        "jurisdiction",
        "office_public_id",
        "office_name",
        "district",
        "seat_name",
        "is_partisan",
        "contest_type",
        "review_status",
        "created_at",
        "updated_at",
    ]

    def rows() -> RowGenerator:
        qs = (
            Race.objects.select_related("election", "election__jurisdiction", "office", "district")
            .order_by("id")
            .iterator(chunk_size=500)
        )
        for r in qs:
            yield [
                r.public_id,
                r.election.public_id,
                r.election.name,
                r.election.date,
                r.election.election_type,
                str(r.election.jurisdiction),
                r.office.public_id,
                r.office.name,
                str(r.district) if r.district_id else "",
                r.seat_name,
                r.is_partisan,
                r.contest_type,
                r.review_status,
                r.created_at,
                r.updated_at,
            ]

    return header, rows()


def _person_jurisdiction_context(person_ids: list[int]) -> tuple[dict[int, set[str]], set[int], set[int]]:
    j_names: dict[int, set[str]] = defaultdict(set)
    official_ids: set[int] = set()
    candidate_ids: set[int] = set()
    for term in (
        OfficeholderTerm.objects.filter(person_id__in=person_ids)
        .select_related("jurisdiction")
        .iterator(chunk_size=500)
    ):
        official_ids.add(term.person_id)
        j_names[term.person_id].add(str(term.jurisdiction))
    for cand in (
        Candidacy.objects.filter(person_id__in=person_ids)
        .select_related("race__election__jurisdiction")
        .iterator(chunk_size=500)
    ):
        candidate_ids.add(cand.person_id)
        j_names[cand.person_id].add(str(cand.race.election.jurisdiction))
    return j_names, official_ids, candidate_ids


def _iter_all_emails() -> tuple[list[str], RowGenerator]:
    header = [
        "email_source",
        "email",
        "label_or_field",
        "person_public_id",
        "person_display_name",
        "is_official",
        "is_candidate",
        "related_jurisdictions",
        "submission_status",
        "submission_profile_role",
        "submission_jurisdiction_name",
        "contact_review_status",
        "contact_is_public",
    ]

    def rows() -> RowGenerator:
        base_cm = ContactMethod.objects.filter(contact_type=ContactType.EMAIL)
        person_ids = list(base_cm.values_list("person_id", flat=True).distinct())
        j_names, official_ids, candidate_ids = _person_jurisdiction_context(person_ids)

        for cm in base_cm.select_related("person").order_by("id").iterator(chunk_size=500):
            jn = j_names.get(cm.person_id, set())
            yield [
                "person_contact",
                (cm.value or "").strip(),
                cm.label or "",
                cm.person.public_id,
                cm.person.display_name,
                cm.person_id in official_ids,
                cm.person_id in candidate_ids,
                "; ".join(sorted(jn)),
                "",
                "",
                "",
                cm.review_status,
                cm.is_public,
            ]

        for sub in ProfileSubmission.objects.order_by("id").iterator(chunk_size=500):
            se = (sub.submitter_email or "").strip()
            ce = (sub.contact_email or "").strip()
            if se:
                yield [
                    "profile_submission",
                    se,
                    "submitter_email",
                    sub.created_person.public_id if sub.created_person_id else "",
                    sub.display_submitted_name(),
                    sub.profile_role == "official",
                    sub.profile_role == "candidate",
                    sub.jurisdiction_name or "",
                    sub.status,
                    sub.profile_role,
                    sub.jurisdiction_name or "",
                    "",
                    "",
                ]
            if ce and ce.lower() != se.lower():
                yield [
                    "profile_submission",
                    ce,
                    "contact_email",
                    sub.created_person.public_id if sub.created_person_id else "",
                    sub.display_submitted_name(),
                    sub.profile_role == "official",
                    sub.profile_role == "candidate",
                    sub.jurisdiction_name or "",
                    sub.status,
                    sub.profile_role,
                    sub.jurisdiction_name or "",
                    "",
                    "",
                ]

    return header, rows()


EXPORT_REGISTRY: dict[str, tuple[str, Callable[[], tuple[list[str], RowGenerator]]]] = {
    "officials": ("officials", _iter_officials),
    "candidates": ("candidates", _iter_candidacies),
    "persons": ("persons", _iter_persons),
    "races": ("races", _iter_races),
    "emails": ("all-emails", _iter_all_emails),
}


@staff_member_required
def staff_csv_export(request, export_key: str) -> StreamingHttpResponse:
    if export_key not in EXPORT_REGISTRY:
        raise Http404("Unknown export.")
    stem, factory = EXPORT_REGISTRY[export_key]
    header, rows = factory()
    return _csv_response(stem, header, rows)
