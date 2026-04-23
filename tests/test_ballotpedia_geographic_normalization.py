from django.utils import timezone

from apps.elections.models import Candidacy, Election, ElectionType, Race
from apps.geo.models import Jurisdiction
from apps.ingestion.models import Provider, SyncRun, SyncStatus
from apps.ingestion.normalizers.ballotpedia_geographic import (
    district_matches_amarillo_metro,
    normalize_ballotpedia_elections_by_point,
    normalize_ballotpedia_elections_by_state_filtered,
)
from apps.people.models import Person


def test_district_matches_amarillo_metro():
    assert district_matches_amarillo_metro({"name": "Potter County", "type": "County", "races": []})
    assert not district_matches_amarillo_metro({"name": "Dallas County", "type": "County", "races": []})


def test_normalize_ballotpedia_elections_by_point_minimal(db):
    run = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.SUCCESS, finished_at=timezone.now())
    payload = {
        "success": True,
        "data": {
            "elections": [
                {
                    "date": "2026-05-02",
                    "districts": [
                        {
                            "id": 1,
                            "name": "Texas",
                            "type": "State",
                            "state": "TX",
                            "precise_boundary": True,
                            "races": [
                                {
                                    "id": 900001,
                                    "office": {
                                        "id": 101,
                                        "name": "Texas Railroad Commission",
                                        "level": "State",
                                        "branch": "Executive",
                                        "is_partisan": "Partisan all",
                                        "seat": "Place 1",
                                        "url": None,
                                        "office_district": 1,
                                    },
                                    "office_district": 1,
                                    "url": "https://ballotpedia.org/Example_election",
                                    "stage_type": "General",
                                    "candidates": [
                                        {
                                            "id": 200001,
                                            "race": 900001,
                                            "party_affiliation": [{"id": 1, "name": "Republican Party"}],
                                            "is_incumbent": False,
                                            "is_write_in": False,
                                            "cand_status": "Running",
                                            "person": {
                                                "id": 300001,
                                                "name": "Alex Example",
                                                "first_name": "Alex",
                                                "last_name": "Example",
                                                "url": "https://ballotpedia.org/Alex_Example",
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }

    normalize_ballotpedia_elections_by_point(sync_run=run, api_payload=payload)

    assert Election.objects.filter(date="2026-05-02").exists()
    assert Race.objects.filter(office__name__icontains="Railroad").exists()
    assert Person.objects.filter(last_name="Example").exists()
    assert Candidacy.objects.exists()
    assert Jurisdiction.objects.filter(state="TX", name="Texas").exists()


def test_normalize_ballotpedia_elections_by_point_runoff_uses_race_stage_type(db):
    """Ballotpedia ``elections_by_point`` does not set ``stage_type`` on the election object — only on races."""
    run = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.SUCCESS, finished_at=timezone.now())
    payload = {
        "success": True,
        "data": {
            "elections": [
                {
                    "date": "2025-12-06",
                    "districts": [
                        {
                            "id": 2,
                            "name": "Potter County",
                            "type": "County",
                            "state": "TX",
                            "precise_boundary": True,
                            "races": [
                                {
                                    "id": 910001,
                                    "office": {
                                        "name": "Potter County Commissioner Precinct 2",
                                        "level": "Local",
                                        "branch": "Executive",
                                        "is_partisan": "Partisan all",
                                        "seat": "",
                                    },
                                    "stage_type": "Runoff",
                                    "candidates": [],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }

    normalize_ballotpedia_elections_by_point(sync_run=run, api_payload=payload)

    assert Election.objects.filter(
        date="2025-12-06", election_type=ElectionType.RUNOFF, jurisdiction__name="Potter County"
    ).exists()


def test_normalize_ballotpedia_elections_by_state_filtered_skips_non_metro(db):
    run = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.SUCCESS, finished_at=timezone.now())
    payload = {
        "success": True,
        "data": {
            "election_date": "2025-05-03",
            "districts": [
                {
                    "name": "Harris County",
                    "type": "County",
                    "state": "TX",
                    "races": [{"id": 999001, "office": {"name": "Harris County Clerk"}, "candidates": []}],
                },
                {
                    "name": "Potter County",
                    "type": "County",
                    "state": "TX",
                    "races": [
                        {
                            "id": 999002,
                            "office": {
                                "id": 501,
                                "name": "Potter County Commissioner Precinct 1",
                                "level": "Local",
                                "branch": "Executive",
                                "is_partisan": "Partisan all",
                                "seat": "",
                            },
                            "stage_type": "General",
                            "candidates": [
                                {
                                    "id": 888001,
                                    "party_affiliation": [{"name": "Republican Party"}],
                                    "is_incumbent": True,
                                    "cand_status": "Won",
                                    "person": {
                                        "id": 777001,
                                        "name": "Metro Only",
                                        "first_name": "Metro",
                                        "last_name": "Only",
                                        "url": "https://ballotpedia.org/Metro_Only",
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }
    normalize_ballotpedia_elections_by_state_filtered(sync_run=run, api_payload=payload)
    assert Person.objects.filter(last_name="Only").exists()
    assert not Person.objects.filter(last_name="Harris").exists()
