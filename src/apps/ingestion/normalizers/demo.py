from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.elections.models import (
    Candidacy,
    CandidacyStatus,
    Election,
    ElectionType,
    OfficeholderTerm,
    Race,
    TermStatus,
)
from apps.geo.models import District, DistrictType, Jurisdiction, JurisdictionType
from apps.ingestion.models import Provider, SourceRecord, SyncRun
from apps.ingestion.priority import priority
from apps.media.models import VideoEmbed, VideoProvider, is_safe_youtube_url
from apps.offices.models import Office, OfficeBranch, OfficeLevel
from apps.people.models import (
    ContactMethod,
    ContactType,
    ExternalLink,
    ExternalLinkKind,
    Party,
    Person,
    SocialLink,
    SocialPlatform,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        y, m, d = [int(x) for x in value.split("-")]
        return date(y, m, d)
    except Exception:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _party_from_any(value: str | None) -> str:
    v = (value or "").strip().lower()
    mapping = {
        "democrat": Party.DEMOCRATIC,
        "democratic": Party.DEMOCRATIC,
        "republican": Party.REPUBLICAN,
        "gop": Party.REPUBLICAN,
        "independent": Party.INDEPENDENT,
        "libertarian": Party.LIBERTARIAN,
        "green": Party.GREEN,
        "nonpartisan": Party.NONPARTISAN,
        "unknown": Party.UNKNOWN,
    }
    return mapping.get(v, Party.OTHER if v else Party.UNKNOWN)


def _record_source(
    *,
    provider: Provider,
    external_id: str,
    payload: dict[str, Any],
    sync_run: SyncRun,
    normalized_obj: Any,
    fetched_at: datetime,
    source_url: str = "",
    source_name: str = "",
) -> SourceRecord:
    sha = SourceRecord.compute_sha256(payload)
    sr, _ = SourceRecord.objects.get_or_create(
        provider=provider,
        external_id=external_id,
        payload_sha256=sha,
        defaults={
            "payload": payload,
            "fetched_at": fetched_at,
            "source_url": source_url,
            "source_name": source_name,
            "sync_run": sync_run,
        },
    )
    if normalized_obj is not None:
        ct = ContentType.objects.get_for_model(normalized_obj.__class__)
        if sr.normalized_content_type_id != ct.id or sr.normalized_object_id != normalized_obj.id:
            sr.normalized_content_type = ct
            sr.normalized_object_id = normalized_obj.id
            sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])
    return sr


@transaction.atomic
def normalize_demo_record(*, provider: Provider, payload: dict[str, Any], sync_run: SyncRun) -> None:
    """
    Demo normalization contract.

    Each payload should include some or all of:
      - person, jurisdiction, district, office, term, election, race, candidacy, contacts, links, socials, videos
    Each nested entity MAY include an `external_id` for SourceRecord attribution.
    """
    fetched_at = timezone.now()
    source_url = str(payload.get("source_url") or "")
    source_name = str(payload.get("source_name") or "")

    jurisdiction_obj = None
    j = payload.get("jurisdiction") or {}
    if j:
        jurisdiction_obj, _ = Jurisdiction.objects.get_or_create(
            state=(j.get("state") or "").upper(),
            jurisdiction_type=j.get("jurisdiction_type") or JurisdictionType.OTHER,
            name=j.get("name") or "Unknown jurisdiction",
            county=j.get("county") or "",
            city=j.get("city") or "",
            defaults={},
        )
        if j.get("external_id"):
            _record_source(
                provider=provider,
                external_id=str(j["external_id"]),
                payload=j,
                sync_run=sync_run,
                normalized_obj=jurisdiction_obj,
                fetched_at=fetched_at,
                source_url=source_url,
                source_name=source_name,
            )

    district_obj = None
    d = payload.get("district") or {}
    if d and jurisdiction_obj:
        district_obj, _ = District.objects.get_or_create(
            jurisdiction=jurisdiction_obj,
            district_type=d.get("district_type") or DistrictType.OTHER,
            name=d.get("name") or "Unknown district",
            number=d.get("number") or "",
            defaults={},
        )
        if d.get("external_id"):
            _record_source(
                provider=provider,
                external_id=str(d["external_id"]),
                payload=d,
                sync_run=sync_run,
                normalized_obj=district_obj,
                fetched_at=fetched_at,
                source_url=source_url,
                source_name=source_name,
            )

    office_obj = None
    o = payload.get("office") or {}
    if o and jurisdiction_obj:
        office_obj, _ = Office.objects.get_or_create(
            jurisdiction=jurisdiction_obj,
            name=o.get("name") or "Unknown office",
            level=o.get("level") or OfficeLevel.LOCAL,
            branch=o.get("branch") or OfficeBranch.OTHER,
            defaults={"is_partisan": bool(o.get("is_partisan") or False)},
        )
        changed = False
        if office_obj.description == "" and o.get("description"):
            office_obj.description = str(o["description"])
            changed = True
        if bool(o.get("is_partisan")) != office_obj.is_partisan:
            office_obj.is_partisan = bool(o.get("is_partisan"))
            changed = True
        if office_obj.default_district_id is None and district_obj:
            office_obj.default_district = district_obj
            changed = True
        if changed:
            office_obj.save()

        if o.get("external_id"):
            _record_source(
                provider=provider,
                external_id=str(o["external_id"]),
                payload=o,
                sync_run=sync_run,
                normalized_obj=office_obj,
                fetched_at=fetched_at,
                source_url=source_url,
                source_name=source_name,
            )

    p = payload.get("person") or {}
    person_obj = None
    if p:
        person_external_id = str(p.get("external_id") or payload.get("external_id") or "").strip()
        if person_external_id:
            ct_person = ContentType.objects.get_for_model(Person)
            existing = (
                # Demo fixtures reuse IDs across providers; reconcile to a single Person when possible.
                SourceRecord.objects.filter(external_id=person_external_id, normalized_content_type=ct_person)
                .order_by("-fetched_at")
                .first()
            )
            if existing and existing.normalized_object_id:
                person_obj = Person.objects.filter(id=existing.normalized_object_id).first()

        if person_obj is None:
            person_obj = Person.objects.create(
                first_name=str(p.get("first_name") or ""),
                preferred_name=str(p.get("preferred_name") or ""),
                middle_name=str(p.get("middle_name") or ""),
                last_name=str(p.get("last_name") or ""),
                suffix=str(p.get("suffix") or ""),
            )

        existing_source_providers = (
            SourceRecord.objects.filter(
                normalized_content_type=ContentType.objects.get_for_model(Person),
                normalized_object_id=person_obj.id,
            )
            .values_list("provider", flat=True)
            .distinct()
        )
        best_priority = min([priority(x) for x in existing_source_providers] or [1000])
        can_override = priority(provider) <= best_priority

        changed = False
        incoming_party = _party_from_any(str(p.get("party") or ""))
        incoming_party_other = str(p.get("party_other") or (p.get("party") if incoming_party == Party.OTHER else "") or "")
        if person_obj.manual_party:
            pass
        else:
            if incoming_party not in {Party.UNKNOWN, ""} and (
                (person_obj.party in {Party.UNKNOWN, ""}) or (can_override and person_obj.party != incoming_party)
            ):
                person_obj.party = incoming_party
                person_obj.party_other = incoming_party_other if incoming_party == Party.OTHER else ""
                changed = True

        incoming_photo = str(p.get("photo_url") or "")
        if incoming_photo and not person_obj.manual_photo_url and (not person_obj.photo_url or can_override):
            person_obj.photo_url = incoming_photo
            changed = True

        if changed:
            person_obj.save()

        if person_external_id:
            _record_source(
                provider=provider,
                external_id=person_external_id,
                payload=p,
                sync_run=sync_run,
                normalized_obj=person_obj,
                fetched_at=fetched_at,
                source_url=source_url,
                source_name=source_name,
            )

    term = payload.get("term") or {}
    if term and person_obj and office_obj and jurisdiction_obj:
        start_date = _parse_date(term.get("start_date"))
        end_date = _parse_date(term.get("end_date"))
        status = term.get("status") or TermStatus.UNKNOWN
        party = _party_from_any(term.get("party"))
        party_other = str(term.get("party_other") or "")

        OfficeholderTerm.objects.get_or_create(
            person=person_obj,
            office=office_obj,
            start_date=start_date,
            end_date=end_date,
            defaults={
                "jurisdiction": jurisdiction_obj,
                "district": district_obj,
                "status": status,
                "party": party,
                "party_other": party_other,
            },
        )

    election_obj = None
    e = payload.get("election") or {}
    if e and jurisdiction_obj:
        election_obj, _ = Election.objects.get_or_create(
            jurisdiction=jurisdiction_obj,
            date=_parse_date(e.get("date")) or date.today(),
            election_type=e.get("election_type") or ElectionType.GENERAL,
            defaults={"name": e.get("name") or "Election"},
        )

    race_obj = None
    r = payload.get("race") or {}
    if r and election_obj and office_obj:
        race_obj, _ = Race.objects.get_or_create(
            election=election_obj,
            office=office_obj,
            district=district_obj,
            seat_name=str(r.get("seat_name") or ""),
            defaults={"is_partisan": bool(r.get("is_partisan") or False)},
        )

    cand = payload.get("candidacy") or {}
    if cand and person_obj and race_obj:
        Candidacy.objects.get_or_create(
            race=race_obj,
            person=person_obj,
            defaults={
                "status": cand.get("status") or CandidacyStatus.RUNNING,
                "party": _party_from_any(cand.get("party")),
                "party_other": str(cand.get("party_other") or ""),
                "is_incumbent": bool(cand.get("is_incumbent") or False),
                "is_challenger": bool(cand.get("is_challenger") or False),
            },
        )

    for c in payload.get("contacts") or []:
        if not person_obj:
            continue
        ct = str(c.get("contact_type") or "").lower()
        if ct not in {x[0] for x in ContactType.choices}:
            continue
        value = str(c.get("value") or "").strip()
        if not value:
            continue
        ContactMethod.objects.get_or_create(
            person=person_obj,
            contact_type=ct,
            value=value,
            defaults={"label": str(c.get("label") or ""), "is_public": bool(c.get("is_public", True))},
        )

    for link in payload.get("external_links") or []:
        if not person_obj:
            continue
        url = str(link.get("url") or "").strip()
        if not url:
            continue
        kind = str(link.get("kind") or ExternalLinkKind.OTHER)
        if kind not in {x[0] for x in ExternalLinkKind.choices}:
            kind = ExternalLinkKind.OTHER
        ExternalLink.objects.get_or_create(
            person=person_obj,
            kind=kind,
            url=url,
            defaults={"label": str(link.get("label") or "")},
        )

    for s in payload.get("social_links") or []:
        if not person_obj:
            continue
        url = str(s.get("url") or "").strip()
        if not url:
            continue
        platform = str(s.get("platform") or SocialPlatform.OTHER)
        if platform not in {x[0] for x in SocialPlatform.choices}:
            platform = SocialPlatform.OTHER
        SocialLink.objects.get_or_create(
            person=person_obj,
            platform=platform,
            url=url,
            defaults={"handle": str(s.get("handle") or "")},
        )

    for v in payload.get("videos") or []:
        provider_value = str(v.get("provider") or VideoProvider.YOUTUBE)
        provider_video_id = str(v.get("provider_video_id") or "").strip()
        if not provider_video_id:
            continue
        if provider_value != VideoProvider.YOUTUBE:
            continue
        source = str(v.get("source_url") or "")
        if source and not is_safe_youtube_url(source):
            source = ""
        obj, _ = VideoEmbed.objects.get_or_create(
            provider=provider_value,
            provider_video_id=provider_video_id,
            defaults={
                "person": person_obj,
                "title": str(v.get("title") or ""),
                "thumbnail_url": str(v.get("thumbnail_url") or ""),
                "published_at": _parse_datetime(v.get("published_at")),
                "source_url": source,
                "is_approved": bool(v.get("is_approved") or False),
            },
        )
        if obj.person_id is None and person_obj:
            obj.person = person_obj
            obj.save(update_fields=["person", "updated_at"])

