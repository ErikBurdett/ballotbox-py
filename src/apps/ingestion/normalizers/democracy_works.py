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
from apps.geo.jurisdiction_canonical import get_or_create_canonical_city, get_or_create_canonical_county
from apps.geo.models import District, DistrictType, Jurisdiction, JurisdictionType
from apps.ingestion.models import Provider, SourceRecord, SyncRun
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


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    digits = "".join([c for c in s if c.isdigit()])
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _slug_to_title(s: str) -> str:
    return " ".join([p.capitalize() for p in s.replace("_", " ").replace("-", " ").split() if p]).strip()


def _party_from_affiliations(values: list[str] | None) -> tuple[str, str]:
    v = (values or [])
    if not v:
        return Party.UNKNOWN, ""
    first = (v[0] or "").strip()
    key = first.lower()
    mapping = {
        "democratic": Party.DEMOCRATIC,
        "democrat": Party.DEMOCRATIC,
        "republican": Party.REPUBLICAN,
        "independent": Party.INDEPENDENT,
        "libertarian": Party.LIBERTARIAN,
        "green": Party.GREEN,
        "nonpartisan": Party.NONPARTISAN,
        "non-partisan": Party.NONPARTISAN,
        "unaﬃliated": Party.INDEPENDENT,
        "unaffiliated": Party.INDEPENDENT,
    }
    party = mapping.get(key, Party.OTHER if first else Party.UNKNOWN)
    return party, first if party == Party.OTHER else ""


def _candidacy_status(value: str | None) -> str:
    v = (value or "").strip().lower()
    mapping = {
        "running": CandidacyStatus.RUNNING,
        "declared": CandidacyStatus.DECLARED,
        "won": CandidacyStatus.WON,
        "lost": CandidacyStatus.LOST,
        "withdrew": CandidacyStatus.WITHDREW,
        "disqualified": CandidacyStatus.DISQUALIFIED,
    }
    return mapping.get(v, CandidacyStatus.UNKNOWN)


def _office_level(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in {c[0] for c in OfficeLevel.choices}:
        return v
    # DW contest.level is usually federal/state/county/local already.
    return OfficeLevel.LOCAL


def _office_branch(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in {c[0] for c in OfficeBranch.choices}:
        return v
    return OfficeBranch.OTHER


def _district_type(value: str | None, ocd_id: str) -> str:
    v = (value or "").strip()
    slug = (v or "").lower()
    # DW districtType values are not 1:1 with our enum; keep it conservative.
    if "congress" in slug:
        return DistrictType.CONGRESSIONAL
    if "statehouse" in slug or "state_house" in slug:
        return DistrictType.STATE_HOUSE
    if "statesenate" in slug or "state_senate" in slug:
        return DistrictType.STATE_SENATE
    if "school" in slug:
        return DistrictType.SCHOOL_BOARD
    if "county" in slug:
        return DistrictType.COUNTY
    if "city" in slug or "town" in slug or "municipal" in slug:
        return DistrictType.CITY_COUNCIL
    # Fallback: infer from OCD ID segments
    if "/congressional_district:" in ocd_id:
        return DistrictType.CONGRESSIONAL
    return DistrictType.OTHER


def _jurisdiction_from_ocd(ocd_id: str) -> Jurisdiction:
    """
    Create a best-effort Jurisdiction from an Open Civic Data division id.
    """
    ocd = (ocd_id or "").strip()
    parts = [p for p in ocd.split("/") if ":" in p]
    state = ""
    county = ""
    city = ""
    jurisdiction_type = JurisdictionType.OTHER
    name = "Unknown"

    for p in parts:
        if p.startswith("state:"):
            state = p.split(":", 1)[1].upper()
        elif p.startswith("county:"):
            county = _slug_to_title(p.split(":", 1)[1])
        elif p.startswith("place:"):
            city = _slug_to_title(p.split(":", 1)[1])

    if city:
        return get_or_create_canonical_city(state=state or "US", raw_name=city)
    if county:
        return get_or_create_canonical_county(state=state or "US", raw_name=f"{county} County")
    if state:
        jurisdiction_type = JurisdictionType.STATE
        name = state
    else:
        jurisdiction_type = JurisdictionType.OTHER
        name = "Unknown"

    obj, _ = Jurisdiction.objects.get_or_create(
        state=state or "US",
        jurisdiction_type=jurisdiction_type,
        name=name,
        county=county,
        city=city,
    )
    return obj


def _maybe_social_url(platform: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith("http://") or v.startswith("https://"):
        return v
    # Handles -> URLs for a small allowlist.
    if platform in {SocialPlatform.X, SocialPlatform.TWITTER}:
        handle = v.lstrip("@")
        return f"https://x.com/{handle}"
    if platform == SocialPlatform.INSTAGRAM:
        handle = v.lstrip("@")
        return f"https://www.instagram.com/{handle}/"
    if platform == SocialPlatform.FACEBOOK:
        handle = v.strip("/")
        return f"https://www.facebook.com/{handle}"
    if platform == SocialPlatform.LINKEDIN:
        return v
    if platform == SocialPlatform.YOUTUBE:
        return v
    return ""


def _record_source(
    *,
    sync_run: SyncRun,
    external_id: str,
    payload: dict[str, Any],
    normalized_obj: Any | None,
    fetched_at: datetime,
    source_url: str = "",
) -> None:
    sha = SourceRecord.compute_sha256(payload)
    su = (source_url or "").strip()
    if not su:
        try:
            su = str(payload.get("canonicalUrl") or payload.get("canonical_url") or "").strip()
        except Exception:
            su = ""
    sr, _ = SourceRecord.objects.get_or_create(
        provider=Provider.DEMOCRACY_WORKS,
        external_id=external_id,
        payload_sha256=sha,
        defaults={
            "payload": payload,
            "fetched_at": fetched_at,
            "source_url": su,
            "source_name": "Democracy Works",
            "sync_run": sync_run,
        },
    )
    if su and sr.source_url != su:
        sr.source_url = su
        sr.save(update_fields=["source_url", "updated_at"])
    if normalized_obj is not None:
        ct = ContentType.objects.get_for_model(normalized_obj.__class__)
        if sr.normalized_content_type_id != ct.id or sr.normalized_object_id != normalized_obj.id:
            sr.normalized_content_type = ct
            sr.normalized_object_id = normalized_obj.id
            sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])

def _get_or_create_person_for_candidate(*, can_id: str, candidate_payload: dict[str, Any], fetched_at: datetime, sync_run: SyncRun) -> Person:
    ct_person = ContentType.objects.get_for_model(Person)
    person: Person | None = None
    if can_id:
        existing = (
            SourceRecord.objects.filter(
                provider=Provider.DEMOCRACY_WORKS,
                external_id=f"candidate:{can_id}",
                normalized_content_type=ct_person,
            )
            .order_by("-fetched_at")
            .first()
        )
        if existing and existing.normalized_object_id:
            person = Person.objects.filter(id=existing.normalized_object_id).first()

    first = str(candidate_payload.get("firstName") or "").strip()
    last = str(candidate_payload.get("lastName") or "").strip()
    full = str(candidate_payload.get("fullName") or "").strip()
    if not (first or last) and full:
        parts = full.split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]

    if person is None:
        person = Person.objects.create(first_name=first, last_name=last, preferred_name=str(candidate_payload.get("firstName") or "").strip())
    else:
        changed = False
        if not person.first_name and first:
            person.first_name = first
            changed = True
        if not person.last_name and last:
            person.last_name = last
            changed = True
        if changed:
            person.save(update_fields=["first_name", "last_name", "updated_at"])

    # Persist candidate payload → Person SourceRecord for stable identity
    if can_id:
        _record_source(
            sync_run=sync_run,
            external_id=f"candidate:{can_id}",
            payload=candidate_payload,
            normalized_obj=person,
            fetched_at=fetched_at,
        )
    return person


def _extract_contests(election_payload: dict[str, Any]) -> list[dict[str, Any]]:
    # DW may nest ballot data; handle several likely shapes defensively.
    for key in ("contests",):
        v = election_payload.get(key)
        if isinstance(v, list):
            return v
    for key in ("ballotData", "ballot", "ballot_data"):
        container = election_payload.get(key)
        if isinstance(container, dict):
            v = container.get("contests")
            if isinstance(v, list):
                return v
    return []


@transaction.atomic
def normalize_dw_election(*, sync_run: SyncRun, election_payload: dict[str, Any]) -> None:
    fetched_at = timezone.now()

    ocd_id = str(election_payload.get("ocdId") or "")
    election_date = _parse_date(str(election_payload.get("date") or "")) or date.today()
    description = str(election_payload.get("description") or "Election").strip()
    updated_at = _parse_dt(str(election_payload.get("updatedAt") or "")) or fetched_at

    jurisdiction = _jurisdiction_from_ocd(ocd_id)

    election, _ = Election.objects.get_or_create(
        jurisdiction=jurisdiction,
        date=election_date,
        election_type=ElectionType.OTHER,
        defaults={"name": description},
    )
    if election.name != description and description:
        election.name = description
        election.save(update_fields=["name", "updated_at"])

    election.last_verified_at = updated_at
    election.save(update_fields=["last_verified_at", "updated_at"])

    _record_source(
        sync_run=sync_run,
        external_id=f"election:{ocd_id}:{election_date.isoformat()}",
        payload=election_payload,
        normalized_obj=election,
        fetched_at=fetched_at,
    )

    for contest in _extract_contests(election_payload):
        normalize_dw_contest(sync_run=sync_run, election=election, contest_payload=contest)


@transaction.atomic
def normalize_dw_contest(*, sync_run: SyncRun, election: Election, contest_payload: dict[str, Any]) -> None:
    fetched_at = timezone.now()
    contest_id = str(contest_payload.get("id") or "").strip()
    contest_name = str(contest_payload.get("name") or "Contest").strip()
    contest_level = _office_level(str(contest_payload.get("level") or ""))
    contest_branch = _office_branch(str(contest_payload.get("branch") or ""))

    ocd_id = str(contest_payload.get("ocdId") or "")
    jurisdiction = _jurisdiction_from_ocd(ocd_id) if ocd_id else election.jurisdiction

    district_name = str(contest_payload.get("districtName") or "").strip()
    district_type_raw = str(contest_payload.get("districtType") or "").strip()

    district_obj = None
    if district_name:
        district_obj, _ = District.objects.get_or_create(
            jurisdiction=jurisdiction,
            district_type=_district_type(district_type_raw, ocd_id),
            name=district_name,
            number="",
        )
        _record_source(
            sync_run=sync_run,
            external_id=f"district:{ocd_id}:{district_name}",
            payload={"ocdId": ocd_id, "districtName": district_name, "districtType": district_type_raw},
            normalized_obj=district_obj,
            fetched_at=fetched_at,
        )

    office, _ = Office.objects.get_or_create(
        jurisdiction=jurisdiction,
        name=contest_name,
        level=contest_level,
        branch=contest_branch,
        defaults={"is_partisan": False, "district_type": district_obj.district_type if district_obj else ""},
    )
    if district_obj and office.default_district_id is None:
        office.default_district = district_obj
        office.save(update_fields=["default_district", "updated_at"])

    is_partisan = False
    candidates = contest_payload.get("candidates") or []
    if isinstance(candidates, list):
        for c in candidates:
            party, _ = _party_from_affiliations(c.get("partyAffiliation") or [])
            if party not in {Party.UNKNOWN, Party.NONPARTISAN}:
                is_partisan = True
                break
    if office.is_partisan != is_partisan:
        office.is_partisan = is_partisan
        office.save(update_fields=["is_partisan", "updated_at"])

    race, _ = Race.objects.get_or_create(
        election=election,
        office=office,
        district=district_obj,
        seat_name=str(contest_payload.get("title") or "")[:255],
        defaults={"is_partisan": office.is_partisan},
    )
    # DW contest metadata (best-effort)
    race_changed = False
    contest_type = str(contest_payload.get("contestType") or "").strip()
    if contest_type and race.contest_type != contest_type:
        race.contest_type = contest_type
        race_changed = True
    seats = _parse_int(contest_payload.get("seatsUpForElection"))
    if seats is not None and race.seats_up_for_election != seats:
        race.seats_up_for_election = seats
        race_changed = True
    ranked_choice = bool(contest_payload.get("rankedChoice") or False)
    if race.ranked_choice != ranked_choice:
        race.ranked_choice = ranked_choice
        race_changed = True
    rnum = _parse_int(contest_payload.get("rankedChoiceRankNumber"))
    if race.ranked_choice_rank_number != rnum:
        race.ranked_choice_rank_number = rnum
        race_changed = True
    has_primary = bool(contest_payload.get("hasPrimary") or False)
    if race.has_primary != has_primary:
        race.has_primary = has_primary
        race_changed = True
    gdate = _parse_date(str(contest_payload.get("generalDate") or "")) if contest_payload.get("generalDate") else None
    pdate = _parse_date(str(contest_payload.get("primaryDate") or "")) if contest_payload.get("primaryDate") else None
    if race.general_date != gdate:
        race.general_date = gdate
        race_changed = True
    if race.primary_date != pdate:
        race.primary_date = pdate
        race_changed = True

    title = str(contest_payload.get("title") or "").strip()
    if title and race.title != title:
        race.title = title[:255]
        race_changed = True
    body = str(contest_payload.get("body") or "").strip()
    if body and race.body != body:
        race.body = body
        race_changed = True
    about_office = str(contest_payload.get("aboutOffice") or "").strip()
    if about_office and race.about_office != about_office:
        race.about_office = about_office
        race_changed = True

    if race_changed:
        race.save(
            update_fields=[
                "contest_type",
                "seats_up_for_election",
                "ranked_choice",
                "ranked_choice_rank_number",
                "has_primary",
                "primary_date",
                "general_date",
                "title",
                "body",
                "about_office",
                "updated_at",
            ]
        )

    if contest_id:
        _record_source(
            sync_run=sync_run,
            external_id=f"contest:{contest_id}",
            payload=contest_payload,
            normalized_obj=race,
            fetched_at=fetched_at,
        )

    if isinstance(candidates, list):
        for c in candidates:
            normalize_dw_candidate(sync_run=sync_run, race=race, candidate_payload=c)


@transaction.atomic
def normalize_dw_candidate(*, sync_run: SyncRun, race: Race, candidate_payload: dict[str, Any]) -> None:
    fetched_at = timezone.now()
    can_id = str(candidate_payload.get("id") or "").strip()
    person = _get_or_create_person_for_candidate(
        can_id=can_id, candidate_payload=candidate_payload, fetched_at=fetched_at, sync_run=sync_run
    )

    party, party_other = _party_from_affiliations(candidate_payload.get("partyAffiliation") or [])
    if not person.manual_party and party != Party.UNKNOWN and (
        person.party in {Party.UNKNOWN, ""} or person.party != party
    ):
        person.party = party
        person.party_other = party_other
        person.save(update_fields=["party", "party_other", "updated_at"])

    ballotpedia_url = str(candidate_payload.get("ballotpediaUrl") or "").strip()
    if ballotpedia_url:
        ExternalLink.objects.get_or_create(
            person=person,
            kind=ExternalLinkKind.BALLOTPEDIA,
            url=ballotpedia_url,
            defaults={"label": "Ballotpedia"},
        )

    contact = candidate_payload.get("contact") or {}
    campaign = (contact.get("campaign") or {}) if isinstance(contact, dict) else {}
    email = str(campaign.get("email") or "").strip()
    phone = str(campaign.get("phone") or "").strip()
    website = str(campaign.get("website") or "").strip()
    mailing_address = str(campaign.get("mailingAddress") or "").strip()
    if email:
        ContactMethod.objects.get_or_create(person=person, contact_type=ContactType.EMAIL, value=email, defaults={"label": "Campaign email"})
    if phone:
        ContactMethod.objects.get_or_create(person=person, contact_type=ContactType.PHONE, value=phone, defaults={"label": "Campaign phone"})
    if website:
        ContactMethod.objects.get_or_create(person=person, contact_type=ContactType.WEBSITE, value=website, defaults={"label": "Campaign website"})
    if mailing_address:
        ContactMethod.objects.get_or_create(
            person=person,
            contact_type=ContactType.ADDRESS,
            value=mailing_address,
            defaults={"label": "Campaign mailing address"},
        )

    personal = (contact.get("personal") or {}) if isinstance(contact, dict) else {}
    personal_website = str(personal.get("website") or "").strip()
    if personal_website:
        ContactMethod.objects.get_or_create(
            person=person,
            contact_type=ContactType.WEBSITE,
            value=personal_website,
            defaults={"label": "Personal website"},
        )

    socials = {
        SocialPlatform.FACEBOOK: [campaign.get("facebook"), personal.get("facebook")],
        SocialPlatform.TWITTER: [campaign.get("twitter"), personal.get("twitter")],
        SocialPlatform.INSTAGRAM: [campaign.get("instagram"), personal.get("instagram")],
        SocialPlatform.YOUTUBE: [campaign.get("youtube"), personal.get("youtube")],
        SocialPlatform.LINKEDIN: [campaign.get("linkedIn"), personal.get("linkedIn")],
    }
    for platform, raws in socials.items():
        for raw in raws:
            url = _maybe_social_url(platform, str(raw or ""))
            if url:
                SocialLink.objects.get_or_create(person=person, platform=platform, url=url)
                break

    is_incumbent = bool(candidate_payload.get("isIncumbent") or False)
    is_write_in = bool(candidate_payload.get("isWriteIn") or False)
    endorsement_count = _parse_int(candidate_payload.get("endorsementCount"))
    running_mate_full_name = str(candidate_payload.get("runningMateFullName") or "").strip()
    running_mate_title = str(candidate_payload.get("runningMateTitle") or "").strip()
    ranked_choice_round = _parse_int(candidate_payload.get("rankedChoiceVotingRound"))
    status = _candidacy_status(str(candidate_payload.get("status") or ""))

    candidacy, _ = Candidacy.objects.update_or_create(
        race=race,
        person=person,
        defaults={
            "party": party,
            "party_other": party_other,
            "status": status,
            "is_incumbent": is_incumbent,
            "is_challenger": (not is_incumbent),
            "is_write_in": is_write_in,
            "endorsement_count": endorsement_count,
            "running_mate_full_name": running_mate_full_name,
            "running_mate_title": running_mate_title,
            "ranked_choice_voting_round": ranked_choice_round,
        },
    )

    # Best-effort officials population: if DW marks a candidate as incumbent,
    # create a reviewable current term so they show up in the officials directory.
    if is_incumbent:
        term, created = OfficeholderTerm.objects.get_or_create(
            person=person,
            office=race.office,
            start_date=None,
            end_date=None,
            defaults={
                "jurisdiction": race.office.jurisdiction,
                "district": race.district,
                "status": TermStatus.CURRENT,
                "party": party,
                "party_other": party_other,
                "review_notes": "Auto-created from Democracy Works ballot data (incumbent candidate). Verify before relying on it as an official record.",
            },
        )
        if not created and term.jurisdiction_id != race.office.jurisdiction_id:
            term.jurisdiction = race.office.jurisdiction
            term.save(update_fields=["jurisdiction", "updated_at"])

    if can_id:
        _record_source(
            sync_run=sync_run,
            external_id=f"candidacy:{race.id}:{can_id}",
            payload={"race_id": race.id, "candidate_id": can_id, "status": status, "is_incumbent": is_incumbent},
            normalized_obj=candidacy,
            fetched_at=fetched_at,
        )

