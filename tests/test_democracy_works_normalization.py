from django.utils import timezone

from apps.ingestion.models import Provider, SyncRun, SyncStatus
from apps.ingestion.normalizers.democracy_works import normalize_dw_contest, normalize_dw_election
from apps.elections.models import Candidacy, Election, Race
from apps.people.models import ContactMethod, ExternalLink, Person


def test_dw_normalization_creates_election_contest_candidate(db):
    run = SyncRun.objects.create(provider=Provider.DEMOCRACY_WORKS, status=SyncStatus.SUCCESS, finished_at=timezone.now())

    election_payload = {
        "ocdId": "ocd-division/country:us/state:ca",
        "date": "2026-11-03",
        "description": "California General Election",
        "updatedAt": "2026-01-01T00:00:00Z",
        "contests": [
            {
                "id": "co_test",
                "name": "City Council Member Ward 3",
                "level": "local",
                "branch": "legislative",
                "districtName": "Ward 3",
                "districtType": "cityTown",
                "ocdId": "ocd-division/country:us/state:ca/place:demo_city/council_district:3",
                "candidates": [
                    {
                        "id": "can_test",
                        "fullName": "Jordan Kim",
                        "firstName": "Jordan",
                        "lastName": "Kim",
                        "partyAffiliation": ["Democratic"],
                        "isIncumbent": True,
                        "ballotpediaUrl": "https://example.invalid/ballotpedia/jordan-kim",
                        "status": "running",
                        "contact": {"campaign": {"email": "jordan@example.invalid", "phone": "555-0100", "website": "https://example.invalid"}},
                    }
                ],
            }
        ],
    }

    normalize_dw_election(sync_run=run, election_payload=election_payload)

    assert Election.objects.filter(name__icontains="California").exists()
    assert Race.objects.filter(office__name__icontains="City Council").exists()
    assert Person.objects.filter(last_name="Kim").exists()
    assert Candidacy.objects.exists()
    assert ExternalLink.objects.exists()
    assert ContactMethod.objects.exists()

