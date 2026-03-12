from apps.ingestion.models import MergeReview, MergeStatus
from apps.ingestion.tasks import detect_person_duplicates

from .factories import PersonFactory


def test_duplicate_detection_creates_merge_review(db):
    PersonFactory(first_name="Alex", last_name="Rivera")
    PersonFactory(first_name="Alex", last_name="Rivera")

    created = detect_person_duplicates(max_groups=10)
    assert created >= 1
    assert MergeReview.objects.filter(status=MergeStatus.OPEN).count() >= 1

