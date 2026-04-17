from __future__ import annotations

from collections.abc import Callable
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
        y, m, d = [int(x) for x in str(value).split("-")[:3]]
        return date(y, m, d)
    except Exception:
        return None


def _party_from_bp_party_list(party_affiliation: Any) -> tuple[str, str]:
    if not isinstance(party_affiliation, list) or not party_affiliation:
        return Party.UNKNOWN, ""
    first = party_affiliation[0]
    name = ""
    if isinstance(first, dict):
        name = str(first.get("name") or "").strip()
    elif isinstance(first, str):
        name = first.strip()
    if not name:
        return Party.UNKNOWN, ""
    key = name.lower()
    mapping = {
        "democratic party": Party.DEMOCRATIC,
        "democrat": Party.DEMOCRATIC,
        "republican party": Party.REPUBLICAN,
        "republican": Party.REPUBLICAN,
        "independent": Party.INDEPENDENT,
        "libertarian party": Party.LIBERTARIAN,
        "libertarian": Party.LIBERTARIAN,
        "green party": Party.GREEN,
        "green": Party.GREEN,
        "nonpartisan": Party.NONPARTISAN,
        "non-partisan": Party.NONPARTISAN,
    }
    party = mapping.get(key, Party.OTHER)
    return party, name if party == Party.OTHER else ""


def _election_type_from_stage(stage_type: str | None) -> str:
    v = (stage_type or "").strip().lower()
    if "primary" in v:
        return ElectionType.PRIMARY
    if "runoff" in v:
        return ElectionType.RUNOFF
    if "special" in v:
        return ElectionType.SPECIAL
    if "general" in v or v == "":
        return ElectionType.GENERAL
    return ElectionType.OTHER


def _office_level(level: str | None) -> str:
    v = (level or "").strip().lower()
    if v in {c[0] for c in OfficeLevel.choices}:
        return v
    return OfficeLevel.LOCAL


def _office_branch(branch: str | None) -> str:
    v = (branch or "").strip().lower()
    if v in {c[0] for c in OfficeBranch.choices}:
        return v
    return OfficeBranch.OTHER


def _district_type_from_bp(district_type: str | None) -> str:
    t = (district_type or "").lower()
    if "congress" in t:
        return DistrictType.CONGRESSIONAL
    if "state legislative (lower)" in t or "state house" in t:
        return DistrictType.STATE_HOUSE
    if "state legislative (upper)" in t or "state senate" in t:
        return DistrictType.STATE_SENATE
    if "school" in t:
        return DistrictType.SCHOOL_BOARD
    if "county" in t and "subdivision" not in t:
        return DistrictType.COUNTY
    if "city" in t or "town" in t:
        return DistrictType.CITY_COUNCIL
    if "judicial" in t or "court" in t:
        return DistrictType.JUDICIAL
    return DistrictType.OTHER


def _is_partisan_flag(raw: Any) -> bool:
    s = str(raw or "").strip().lower()
    if not s:
        return False
    return "partisan" in s and "non" not in s


def _jurisdiction_federal() -> Jurisdiction:
    obj, _ = Jurisdiction.objects.get_or_create(
        state="US",
        jurisdiction_type=JurisdictionType.OTHER,
        name="United States",
        county="",
        city="",
    )
    return obj


def _jurisdiction_texas() -> Jurisdiction:
    obj, _ = Jurisdiction.objects.get_or_create(
        state="TX",
        jurisdiction_type=JurisdictionType.STATE,
        name="Texas",
        county="",
        city="",
    )
    return obj


def _bp_district_division_kind(dtype: str) -> str:
    """Normalize Ballotpedia district ``type`` strings (casing varies)."""
    d = str(dtype or "").strip().lower()
    if d == "country":
        return "country"
    if d == "state":
        return "state"
    if "county" in d:
        return "county"
    if any(x in d for x in ("city-town", "municipality", "borough", "village", "town", "city")):
        return "local_place"
    return "other"


def _bp_local_place_jurisdiction_type(dtype_lower: str) -> str:
    if "borough" in dtype_lower:
        return JurisdictionType.BOROUGH
    if "village" in dtype_lower:
        return JurisdictionType.VILLAGE
    if "township" in dtype_lower:
        return JurisdictionType.TOWNSHIP
    if "town" in dtype_lower and "city" not in dtype_lower:
        return JurisdictionType.TOWN
    return JurisdictionType.CITY


def _jurisdiction_from_bp_district(district: dict[str, Any]) -> Jurisdiction:
    dtype_raw = str(district.get("type") or "")
    kind = _bp_district_division_kind(dtype_raw)
    name = str(district.get("name") or "").strip()
    st = str(district.get("state") or "").strip().upper() or "TX"

    if kind == "country":
        return _jurisdiction_federal()
    if kind == "state":
        if st == "TX":
            return _jurisdiction_texas()
        obj, _ = Jurisdiction.objects.get_or_create(
            state=st,
            jurisdiction_type=JurisdictionType.STATE,
            name=name or st,
            county="",
            city="",
        )
        return obj
    if kind == "county" and name:
        return get_or_create_canonical_county(state=st, raw_name=name)
    if kind == "local_place" and name:
        jt = _bp_local_place_jurisdiction_type(dtype_raw.lower())
        return get_or_create_canonical_city(state=st, raw_name=name, jurisdiction_type=jt)

    obj, _ = Jurisdiction.objects.get_or_create(
        state=st,
        jurisdiction_type=JurisdictionType.OTHER,
        name=name or dtype_raw or "Other",
        county="",
        city="",
    )
    return obj


def record_ballotpedia_raw_payload(*, sync_run: SyncRun, external_id: str, api_payload: dict[str, Any]) -> None:
    """Persist full API JSON for auditing (no normalized object)."""
    _record_bp(
        sync_run=sync_run,
        external_id=external_id,
        payload=api_payload,
        normalized_obj=None,
        fetched_at=timezone.now(),
    )


def _record_bp(
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
    sr, _ = SourceRecord.objects.get_or_create(
        provider=Provider.BALLOTPEDIA,
        external_id=external_id,
        payload_sha256=sha,
        defaults={
            "payload": payload,
            "fetched_at": fetched_at,
            "source_url": su,
            "source_name": "Ballotpedia Geographic",
            "sync_run": sync_run,
        },
    )
    if normalized_obj is not None:
        ct = ContentType.objects.get_for_model(normalized_obj.__class__)
        if sr.normalized_content_type_id != ct.id or sr.normalized_object_id != normalized_obj.id:
            sr.normalized_content_type = ct
            sr.normalized_object_id = normalized_obj.id
            sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])


def _candidacy_status_bp(cand_status: str | None) -> str:
    v = (cand_status or "").strip().lower()
    mapping = {
        "running": CandidacyStatus.RUNNING,
        "declared": CandidacyStatus.DECLARED,
        "won": CandidacyStatus.WON,
        "lost": CandidacyStatus.LOST,
        "withdrew": CandidacyStatus.WITHDREW,
        "disqualified": CandidacyStatus.DISQUALIFIED,
    }
    return mapping.get(v, CandidacyStatus.UNKNOWN)


def _get_or_create_person_bp_person(
    *, person_payload: dict[str, Any], fetched_at: datetime, sync_run: SyncRun
) -> Person:
    pid = str(person_payload.get("id") or "").strip()
    ct_person = ContentType.objects.get_for_model(Person)
    person: Person | None = None
    if pid:
        existing = (
            SourceRecord.objects.filter(
                provider=Provider.BALLOTPEDIA,
                external_id=f"ballotpedia:person:{pid}",
                normalized_content_type=ct_person,
            )
            .order_by("-fetched_at")
            .first()
        )
        if existing and existing.normalized_object_id:
            person = Person.objects.filter(id=existing.normalized_object_id).first()

    first = str(person_payload.get("first_name") or "").strip()
    last = str(person_payload.get("last_name") or "").strip()
    full = str(person_payload.get("name") or "").strip()
    if not (first or last) and full:
        parts = full.split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]

    if person is None:
        person = Person.objects.create(first_name=first, last_name=last, preferred_name=first)
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

    if pid:
        _record_bp(
            sync_run=sync_run,
            external_id=f"ballotpedia:person:{pid}",
            payload=person_payload,
            normalized_obj=person,
            fetched_at=fetched_at,
            source_url=str(person_payload.get("url") or ""),
        )

    url = str(person_payload.get("url") or "").strip()
    if url:
        ExternalLink.objects.get_or_create(
            person=person,
            kind=ExternalLinkKind.BALLOTPEDIA,
            url=url,
            defaults={"label": "Ballotpedia"},
        )

    return person


def _apply_bp_contact_rows(person: Person, rows: Any) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("contact") or "").strip()
        if not raw:
            continue
        ct = str(row.get("contact_type") or "").strip().lower()
        if ct == "email":
            ContactMethod.objects.get_or_create(
                person=person, contact_type=ContactType.EMAIL, value=raw, defaults={"label": "Ballotpedia"}
            )
        elif ct == "phone":
            ContactMethod.objects.get_or_create(
                person=person, contact_type=ContactType.PHONE, value=raw, defaults={"label": "Ballotpedia"}
            )
        elif ct == "website":
            ContactMethod.objects.get_or_create(
                person=person, contact_type=ContactType.WEBSITE, value=raw, defaults={"label": "Ballotpedia"}
            )


def _apply_bp_social_dict(person: Person, social: Any) -> None:
    if not isinstance(social, dict):
        return
    mapping = [
        (SocialPlatform.FACEBOOK, social.get("facebook")),
        (SocialPlatform.TWITTER, social.get("twitter") or social.get("x")),
        (SocialPlatform.INSTAGRAM, social.get("instagram")),
        (SocialPlatform.YOUTUBE, social.get("youtube")),
        (SocialPlatform.LINKEDIN, social.get("linkedin") or social.get("linkedIn")),
    ]
    for platform, raw in mapping:
        u = str(raw or "").strip()
        if u.startswith("http"):
            SocialLink.objects.get_or_create(person=person, platform=platform, url=u)
        elif u and platform in {SocialPlatform.TWITTER, SocialPlatform.INSTAGRAM, SocialPlatform.FACEBOOK}:
            h = u.lstrip("@")
            if platform == SocialPlatform.TWITTER:
                SocialLink.objects.get_or_create(
                    person=person, platform=platform, url=f"https://x.com/{h}"
                )
            elif platform == SocialPlatform.INSTAGRAM:
                SocialLink.objects.get_or_create(
                    person=person, platform=platform, url=f"https://www.instagram.com/{h}/"
                )
            else:
                SocialLink.objects.get_or_create(
                    person=person, platform=platform, url=f"https://www.facebook.com/{h}"
                )


def _get_or_create_person_bp_officeholder(
    *, oh: dict[str, Any], fetched_at: datetime, sync_run: SyncRun
) -> Person:
    oid = str(oh.get("id") or "").strip()
    ct_person = ContentType.objects.get_for_model(Person)
    person: Person | None = None
    if oid:
        existing = (
            SourceRecord.objects.filter(
                provider=Provider.BALLOTPEDIA,
                external_id=f"ballotpedia:officeholder:{oid}",
                normalized_content_type=ct_person,
            )
            .order_by("-fetched_at")
            .first()
        )
        if existing and existing.normalized_object_id:
            person = Person.objects.filter(id=existing.normalized_object_id).first()

    full = str(oh.get("name") or "").strip()
    last = str(oh.get("last_name") or "").strip()
    first = ""
    if full and not last:
        parts = full.split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
        elif len(parts) == 1:
            last = parts[0]

    if person is None:
        person = Person.objects.create(first_name=first, last_name=last or full, preferred_name=first)
    else:
        changed = False
        if not person.first_name and first:
            person.first_name = first
            changed = True
        if not person.last_name and (last or full):
            person.last_name = last or person.last_name
            changed = True
        if changed:
            person.save(update_fields=["first_name", "last_name", "updated_at"])

    if oid:
        _record_bp(
            sync_run=sync_run,
            external_id=f"ballotpedia:officeholder:{oid}",
            payload=oh,
            normalized_obj=person,
            fetched_at=fetched_at,
            source_url=str(oh.get("url") or ""),
        )

    url = str(oh.get("url") or "").strip()
    if url:
        ExternalLink.objects.get_or_create(
            person=person,
            kind=ExternalLinkKind.BALLOTPEDIA,
            url=url,
            defaults={"label": "Ballotpedia"},
        )

    _apply_bp_contact_rows(person, oh.get("officeholder_contact_information"))
    _apply_bp_contact_rows(person, oh.get("person_contact_information"))
    _apply_bp_social_dict(person, oh.get("social_media") or oh.get("socialMedia"))

    return person


# Substrings for Ballotpedia ``elections_by_state`` rows to keep (Panhandle / Amarillo metro).
AMARILLO_METRO_SUBSTRINGS: tuple[str, ...] = (
    "amarillo",
    "potter",
    "randall",
    "canyon",
    "river road",
    "bushland",
    "hereford",
    "claude",
    "lake tanglewood",
    "timbercreek",
)


def district_matches_amarillo_metro(district: dict[str, Any]) -> bool:
    parts: list[str] = [str(district.get("name") or ""), str(district.get("type") or "")]
    for race in district.get("races") or []:
        if not isinstance(race, dict):
            continue
        ob = race.get("office") or {}
        if isinstance(ob, dict):
            parts.append(str(ob.get("name") or ""))
            parts.append(str(ob.get("seat") or ""))
    blob = " ".join(parts).lower()
    return any(s in blob for s in AMARILLO_METRO_SUBSTRINGS)


def _normalize_bp_election_block(*, sync_run: SyncRun, election_block: dict[str, Any], fetched_at: datetime) -> None:
    election_date = _parse_date(str(election_block.get("date") or "")) or date.today()
    stage_type = str(election_block.get("stage_type") or election_block.get("type") or "")
    election_type = _election_type_from_stage(stage_type)

    districts = election_block.get("districts") or []
    if not isinstance(districts, list):
        return

    for district in districts:
        if not isinstance(district, dict):
            continue
        jurisdiction = _jurisdiction_from_bp_district(district)
        election, _ = Election.objects.get_or_create(
            jurisdiction=jurisdiction,
            date=election_date,
            election_type=election_type,
            defaults={"name": f"Election {election_date.isoformat()}"},
        )

        district_name = str(district.get("name") or "").strip()
        district_type_raw = str(district.get("type") or "")
        district_obj = None
        if district_name:
            district_obj, _ = District.objects.get_or_create(
                jurisdiction=jurisdiction,
                district_type=_district_type_from_bp(district_type_raw),
                name=district_name,
                number="",
            )

        races = district.get("races") or []
        if not isinstance(races, list):
            continue
        for race_payload in races:
            if not isinstance(race_payload, dict):
                continue
            office_blob = race_payload.get("office") or {}
            if not isinstance(office_blob, dict):
                continue
            office_name = str(office_blob.get("name") or "Office").strip()
            level = _office_level(str(office_blob.get("level") or ""))
            branch = _office_branch(str(office_blob.get("branch") or ""))
            is_partisan = _is_partisan_flag(office_blob.get("is_partisan"))

            office, _ = Office.objects.get_or_create(
                jurisdiction=jurisdiction,
                name=office_name,
                level=level,
                branch=branch,
                defaults={
                    "is_partisan": is_partisan,
                    "district_type": district_obj.district_type if district_obj else "",
                },
            )
            if district_obj and office.default_district_id is None:
                office.default_district = district_obj
                office.save(update_fields=["default_district", "updated_at"])
            if office.is_partisan != is_partisan:
                office.is_partisan = is_partisan
                office.save(update_fields=["is_partisan", "updated_at"])

            seat_name = str(office_blob.get("seat") or "")[:255]
            race, _ = Race.objects.get_or_create(
                election=election,
                office=office,
                district=district_obj,
                seat_name=seat_name,
                defaults={"is_partisan": office.is_partisan},
            )
            rid = str(race_payload.get("id") or "").strip()
            if rid:
                _record_bp(
                    sync_run=sync_run,
                    external_id=f"ballotpedia:race:{rid}",
                    payload=race_payload,
                    normalized_obj=race,
                    fetched_at=fetched_at,
                    source_url=str(race_payload.get("url") or ""),
                )

            stage_type_r = str(race_payload.get("stage_type") or stage_type)
            if stage_type_r:
                if race.contest_type != stage_type_r[:64]:
                    race.contest_type = stage_type_r[:64]
                    race.save(update_fields=["contest_type", "updated_at"])

            cands = race_payload.get("candidates") or []
            if not isinstance(cands, list):
                continue
            for cand in cands:
                if not isinstance(cand, dict):
                    continue
                person_blob = cand.get("person") or {}
                if not isinstance(person_blob, dict):
                    continue
                person = _get_or_create_person_bp_person(
                    person_payload=person_blob, fetched_at=fetched_at, sync_run=sync_run
                )

                party, party_other = _party_from_bp_party_list(cand.get("party_affiliation"))
                if not person.manual_party and party != Party.UNKNOWN and (
                    person.party in {Party.UNKNOWN, ""} or person.party != party
                ):
                    person.party = party
                    person.party_other = party_other
                    person.save(update_fields=["party", "party_other", "updated_at"])

                _apply_bp_contact_rows(person, person_blob.get("person_contact_information"))
                _apply_bp_social_dict(person, person_blob.get("social_media") or person_blob.get("socialMedia"))

                is_incumbent = bool(cand.get("is_incumbent"))
                is_write_in = bool(cand.get("is_write_in"))
                status = _candidacy_status_bp(str(cand.get("cand_status") or ""))

                Candidacy.objects.update_or_create(
                    race=race,
                    person=person,
                    defaults={
                        "party": party,
                        "party_other": party_other,
                        "status": status,
                        "is_incumbent": is_incumbent,
                        "is_challenger": not is_incumbent,
                        "is_write_in": is_write_in,
                    },
                )

                cid = str(cand.get("id") or "").strip()
                if cid:
                    _record_bp(
                        sync_run=sync_run,
                        external_id=f"ballotpedia:candidate:{cid}",
                        payload=cand,
                        normalized_obj=person,
                        fetched_at=fetched_at,
                    )


@transaction.atomic
def normalize_ballotpedia_elections_by_point(*, sync_run: SyncRun, api_payload: dict[str, Any]) -> None:
    fetched_at = timezone.now()
    raw = api_payload.get("data") if isinstance(api_payload, dict) else None
    data = raw if isinstance(raw, dict) else {}
    elections = data.get("elections") or []
    if not isinstance(elections, list):
        return

    for election_block in elections:
        if isinstance(election_block, dict):
            _normalize_bp_election_block(sync_run=sync_run, election_block=election_block, fetched_at=fetched_at)


@transaction.atomic
def normalize_ballotpedia_elections_by_state_filtered(
    *,
    sync_run: SyncRun,
    api_payload: dict[str, Any],
    district_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> None:
    """
    Normalize ``/elections_by_state`` payload (``data.districts`` + ``data.election_date``).

    Defaults to ``district_matches_amarillo_metro`` so statewide pulls stay Panhandle-scoped.
    """
    filt = district_filter or district_matches_amarillo_metro
    fetched_at = timezone.now()
    raw = api_payload.get("data") if isinstance(api_payload, dict) else None
    data = raw if isinstance(raw, dict) else {}
    ed = str(data.get("election_date") or "").strip()
    if not ed:
        return
    districts = data.get("districts") or []
    if not isinstance(districts, list):
        return
    kept = [d for d in districts if isinstance(d, dict) and filt(d)]
    if not kept:
        return
    synthetic = {"date": ed, "districts": kept, "stage_type": str(data.get("stage_type") or "")}
    _normalize_bp_election_block(sync_run=sync_run, election_block=synthetic, fetched_at=fetched_at)


@transaction.atomic
def normalize_ballotpedia_officeholders(*, sync_run: SyncRun, anchor_slug: str, api_payload: dict[str, Any]) -> None:
    fetched_at = timezone.now()
    raw = api_payload.get("data")
    rows: list[Any]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and "elected_officials" in raw:
        rows = [raw]
    else:
        return
    for wrapper in rows:
        if not isinstance(wrapper, dict):
            continue
        eo = wrapper.get("elected_officials") or {}
        if not isinstance(eo, dict):
            continue
        districts = eo.get("districts") or []
        if not isinstance(districts, list):
            continue
        for district in districts:
            if not isinstance(district, dict):
                continue
            jurisdiction = _jurisdiction_from_bp_district(district)
            offices = district.get("offices") or []
            if not isinstance(offices, list):
                continue
            for office_blob in offices:
                if not isinstance(office_blob, dict):
                    continue
                office_name = str(office_blob.get("name") or "Office").strip()
                level = _office_level(str(office_blob.get("level") or ""))
                branch = _office_branch(str(office_blob.get("branch") or ""))
                office, _ = Office.objects.get_or_create(
                    jurisdiction=jurisdiction,
                    name=office_name,
                    level=level,
                    branch=branch,
                    defaults={"is_partisan": False, "district_type": ""},
                )
                district_name = str(district.get("name") or "").strip()
                district_obj = None
                if district_name:
                    district_obj, _ = District.objects.get_or_create(
                        jurisdiction=jurisdiction,
                        district_type=_district_type_from_bp(str(district.get("type") or "")),
                        name=district_name,
                        number="",
                    )
                    if office.default_district_id is None:
                        office.default_district = district_obj
                        office.save(update_fields=["default_district", "updated_at"])

                holders = office_blob.get("officeholders") or []
                if not isinstance(holders, list):
                    continue
                for oh in holders:
                    if not isinstance(oh, dict):
                        continue
                    if str(oh.get("status") or "").strip().lower() != "current":
                        continue
                    person = _get_or_create_person_bp_officeholder(oh=oh, fetched_at=fetched_at, sync_run=sync_run)
                    party, party_other = Party.UNKNOWN, ""
                    pa = oh.get("partisan_affiliation")
                    if isinstance(pa, str) and pa.strip():
                        party, party_other = _party_from_bp_party_list([{"name": pa}])
                    elif isinstance(pa, int):
                        party, party_other = Party.OTHER, f"ballotpedia_party_id:{pa}"

                    OfficeholderTerm.objects.get_or_create(
                        person=person,
                        office=office,
                        start_date=None,
                        end_date=None,
                        defaults={
                            "jurisdiction": jurisdiction,
                            "district": district_obj,
                            "status": TermStatus.CURRENT,
                            "party": party,
                            "party_other": party_other[:128],
                            "review_notes": (
                                f"Ballotpedia officeholders ({anchor_slug}). "
                                "Verify dates and jurisdiction before relying on this record."
                            ),
                        },
                    )
