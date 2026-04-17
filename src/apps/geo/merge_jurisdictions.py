"""
Merge duplicate ``Jurisdiction`` rows (same state + type + slugified name).

Re-points dependent rows and deletes the duplicate jurisdiction records.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.text import slugify

from apps.elections.models import Candidacy, Election, OfficeholderTerm, Race
from apps.geo.models import District, Jurisdiction
from apps.ingestion.models import SourceRecord
from apps.offices.models import Office

logger = logging.getLogger(__name__)


def _reassign_candidacies_merge_races(*, loser: Race, winner: Race) -> None:
    for c in list(Candidacy.objects.filter(race=loser)):
        if Candidacy.objects.filter(race=winner, person=c.person).exists():
            c.delete()
        else:
            c.race = winner
            c.save(update_fields=["race", "updated_at"])


def _merge_races_onto_parallel_office(*, source_office: Office, target_office: Office) -> None:
    for race in list(Race.objects.filter(office=source_office)):
        existing = (
            Race.objects.filter(
                election=race.election,
                office=target_office,
                district=race.district,
                seat_name=race.seat_name,
            )
            .exclude(id=race.id)
            .first()
        )
        if existing:
            _reassign_candidacies_merge_races(loser=race, winner=existing)
            race.delete()
        else:
            race.office = target_office
            race.save(update_fields=["office", "updated_at"])


def _repoint_offices(*, keeper: Jurisdiction, duplicate: Jurisdiction) -> int:
    moved = 0
    for o in list(Office.objects.filter(jurisdiction=duplicate)):
        twin, _ = Office.objects.get_or_create(
            jurisdiction=keeper,
            name=o.name,
            level=o.level,
            branch=o.branch,
            defaults={
                "is_partisan": o.is_partisan,
                "district_type": o.district_type,
                "description": o.description,
                "default_district": o.default_district,
            },
        )
        if twin.default_district_id is None and o.default_district_id:
            twin.default_district = o.default_district
            twin.save(update_fields=["default_district", "updated_at"])
        if not twin.description and o.description:
            twin.description = o.description
            twin.save(update_fields=["description", "updated_at"])
        _merge_races_onto_parallel_office(source_office=o, target_office=twin)
        OfficeholderTerm.objects.filter(office=o).update(office=twin)
        o.delete()
        moved += 1
    return moved


def _repoint_elections(*, keeper: Jurisdiction, duplicate: Jurisdiction) -> int:
    moved = 0
    for e in list(Election.objects.filter(jurisdiction=duplicate)):
        twin, _ = Election.objects.get_or_create(
            jurisdiction=keeper,
            date=e.date,
            election_type=e.election_type,
            defaults={"name": e.name},
        )
        if twin.name != e.name and len(e.name) > len(twin.name or ""):
            twin.name = e.name
            twin.save(update_fields=["name", "updated_at"])
        for race in list(Race.objects.filter(election=e)):
            existing = (
                Race.objects.filter(
                    election=twin,
                    office=race.office,
                    district=race.district,
                    seat_name=race.seat_name,
                )
                .exclude(id=race.id)
                .first()
            )
            if existing:
                _reassign_candidacies_merge_races(loser=race, winner=existing)
                race.delete()
            else:
                race.election = twin
                race.save(update_fields=["election", "updated_at"])
        e.delete()
        moved += 1
    return moved


def _repoint_districts(*, keeper: Jurisdiction, duplicate: Jurisdiction) -> int:
    moved = 0
    for d in list(District.objects.filter(jurisdiction=duplicate)):
        twin = (
            District.objects.filter(
                jurisdiction=keeper,
                district_type=d.district_type,
                name=d.name,
                number=d.number,
            )
            .exclude(id=d.id)
            .first()
        )
        if twin:
            Race.objects.filter(district=d).update(district=twin)
            OfficeholderTerm.objects.filter(district=d).update(district=twin)
            Office.objects.filter(default_district=d).update(default_district=twin)
            d.delete()
        else:
            d.jurisdiction = keeper
            d.save(update_fields=["jurisdiction", "updated_at"])
        moved += 1
    return moved


def _repoint_source_records(*, keeper: Jurisdiction, duplicate: Jurisdiction) -> int:
    ct = ContentType.objects.get_for_model(Jurisdiction)
    return SourceRecord.objects.filter(normalized_content_type=ct, normalized_object_id=duplicate.id).update(
        normalized_object_id=keeper.id
    )


@transaction.atomic
def merge_jurisdiction_into(*, keeper: Jurisdiction, duplicate: Jurisdiction) -> dict[str, int]:
    """Move all references from ``duplicate`` onto ``keeper`` and delete ``duplicate``."""
    if keeper.id == duplicate.id:
        return {"skipped": 1}
    stats: dict[str, int] = {}
    stats["source_records"] = _repoint_source_records(keeper=keeper, duplicate=duplicate)
    stats["jurisdiction_children"] = Jurisdiction.objects.filter(parent=duplicate).update(parent=keeper)
    # Districts before offices so ``Office.default_district`` still resolves while repointing offices.
    stats["districts"] = _repoint_districts(keeper=keeper, duplicate=duplicate)
    stats["officeholder_terms_jurisdiction"] = OfficeholderTerm.objects.filter(jurisdiction=duplicate).update(
        jurisdiction=keeper
    )
    stats["offices"] = _repoint_offices(keeper=keeper, duplicate=duplicate)
    stats["elections"] = _repoint_elections(keeper=keeper, duplicate=duplicate)
    duplicate.delete()
    stats["deleted"] = 1
    return stats


def iter_duplicate_jurisdiction_groups(
    *,
    state: str,
    jurisdiction_types: Iterable[str],
) -> list[list[Jurisdiction]]:
    st = state.upper().strip()
    groups: dict[tuple[str, str, str], list[Jurisdiction]] = {}
    qs = Jurisdiction.objects.filter(state=st, jurisdiction_type__in=list(jurisdiction_types)).order_by("id")
    for j in qs:
        key = (j.state, j.jurisdiction_type, slugify(j.name.lower()))
        groups.setdefault(key, []).append(j)
    return [g for g in groups.values() if len(g) > 1]


def merge_duplicate_groups(
    *,
    state: str,
    jurisdiction_types: Iterable[str],
    dry_run: bool = False,
) -> tuple[int, dict[str, int]]:
    """
    Merge groups of duplicate jurisdictions. Returns ``(groups_merged, aggregate_stats)``.
    """
    agg: dict[str, int] = {}
    merged_groups = 0
    for group in iter_duplicate_jurisdiction_groups(state=state, jurisdiction_types=jurisdiction_types):
        group_sorted = sorted(group, key=lambda x: x.id)
        keeper = group_sorted[0]
        dups = group_sorted[1:]
        if dry_run:
            logger.info("Would merge %s duplicates into id=%s name=%r", len(dups), keeper.id, keeper.name)
            merged_groups += 1
            continue
        for dup in dups:
            stats = merge_jurisdiction_into(keeper=keeper, duplicate=dup)
            for k, v in stats.items():
                agg[k] = agg.get(k, 0) + v
        merged_groups += 1
    return merged_groups, agg
