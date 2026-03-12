from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import PublicIdModel, TimeStampedModel


class Provider(models.TextChoices):
    BALLOTREADY_CIVICENGINE = "ballotready_civicengine", "BallotReady/CivicEngine"
    BALLOTPEDIA = "ballotpedia", "Ballotpedia"
    OPENSTATES = "openstates", "OpenStates"
    OPENFEC = "openfec", "OpenFEC"
    YOUTUBE = "youtube", "YouTube"


class SyncStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    PARTIAL = "partial", "Partial"
    CANCELLED = "cancelled", "Cancelled"


class SyncRun(PublicIdModel, TimeStampedModel):
    provider = models.CharField(max_length=64, choices=Provider.choices, db_index=True)
    status = models.CharField(max_length=32, choices=SyncStatus.choices, default=SyncStatus.RUNNING, db_index=True)

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True)

    stats = models.JSONField(default=dict, blank=True)
    error_text = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["provider", "started_at"])]

    def __str__(self) -> str:
        return f"{self.get_provider_display()} sync · {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class SourceRecord(PublicIdModel, TimeStampedModel):
    provider = models.CharField(max_length=64, choices=Provider.choices, db_index=True)
    external_id = models.CharField(max_length=255, db_index=True)
    source_url = models.URLField(blank=True)
    source_name = models.CharField(max_length=255, blank=True)

    fetched_at = models.DateTimeField(db_index=True)
    payload = models.JSONField()
    payload_sha256 = models.CharField(max_length=64, db_index=True)

    sync_run = models.ForeignKey(SyncRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="records")

    normalized_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    normalized_object_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    normalized_object = GenericForeignKey("normalized_content_type", "normalized_object_id")

    class Meta:
        indexes = [
            models.Index(fields=["provider", "external_id"]),
            models.Index(fields=["payload_sha256"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id", "payload_sha256"], name="uniq_source_payload")
        ]

    @staticmethod
    def compute_sha256(payload: object) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_id}"


class MergeStatus(models.TextChoices):
    OPEN = "open", "Open"
    MERGED = "merged", "Merged"
    REJECTED = "rejected", "Rejected"


class MergeReview(PublicIdModel, TimeStampedModel):
    status = models.CharField(max_length=32, choices=MergeStatus.choices, default=MergeStatus.OPEN, db_index=True)

    candidate_a_content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")
    candidate_a_object_id = models.PositiveBigIntegerField(db_index=True)
    candidate_a = GenericForeignKey("candidate_a_content_type", "candidate_a_object_id")

    candidate_b_content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")
    candidate_b_object_id = models.PositiveBigIntegerField(db_index=True)
    candidate_b = GenericForeignKey("candidate_b_content_type", "candidate_b_object_id")

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="merge_reviews"
    )
    merge_reason = models.TextField(blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"MergeReview {self.public_id} ({self.status})"

