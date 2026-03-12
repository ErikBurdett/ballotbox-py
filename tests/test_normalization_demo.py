from django.utils import timezone

from apps.ingestion.models import Provider, SourceRecord, SyncRun, SyncStatus
from apps.ingestion.normalizers.demo import normalize_demo_record
from apps.people.models import Party, Person


def test_demo_normalization_creates_person_and_source_records(db):
    run = SyncRun.objects.create(provider=Provider.OPENSTATES, status=SyncStatus.SUCCESS, finished_at=timezone.now())

    payload = {
        "external_id": "test-person-1",
        "source_name": "Test provider",
        "source_url": "https://example.invalid/test",
        "jurisdiction": {
            "external_id": "test-jur-1",
            "state": "CA",
            "jurisdiction_type": "city",
            "name": "Test City",
            "county": "Test County",
            "city": "Test City",
        },
        "office": {
            "external_id": "test-office-1",
            "name": "Mayor",
            "level": "local",
            "branch": "executive",
            "is_partisan": False,
        },
        "person": {"external_id": "test-person-1", "first_name": "Pat", "last_name": "Quinn", "party": "unknown"},
        "term": {"status": "current", "start_date": "2024-01-01", "end_date": None, "party": "unknown"},
    }

    normalize_demo_record(provider=Provider.OPENSTATES, payload=payload, sync_run=run)

    person = Person.objects.get(first_name="Pat", last_name="Quinn")
    assert SourceRecord.objects.filter(provider=Provider.OPENSTATES, external_id="test-person-1").exists()
    assert person.public_id is not None


def test_provider_priority_can_override_party(db):
    run_low = SyncRun.objects.create(provider=Provider.OPENSTATES, status=SyncStatus.SUCCESS, finished_at=timezone.now())
    run_high = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.SUCCESS, finished_at=timezone.now())

    payload_low = {
        "external_id": "test-person-2",
        "person": {"external_id": "test-person-2", "first_name": "Sam", "last_name": "Lee", "party": "independent"},
    }
    payload_high = {
        "external_id": "test-person-2",
        "person": {"external_id": "test-person-2", "first_name": "Sam", "last_name": "Lee", "party": "democratic"},
    }

    normalize_demo_record(provider=Provider.OPENSTATES, payload=payload_low, sync_run=run_low)
    person = Person.objects.get(first_name="Sam", last_name="Lee")
    assert person.party == Party.INDEPENDENT

    normalize_demo_record(provider=Provider.BALLOTPEDIA, payload=payload_high, sync_run=run_high)
    person.refresh_from_db()
    assert person.party == Party.DEMOCRATIC

