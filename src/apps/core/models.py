from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True


class ReviewStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    NEEDS_REVIEW = "needs_review", "Needs review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ReviewableModel(TimeStampedModel):
    review_status = models.CharField(
        max_length=32, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW, db_index=True
    )
    last_verified_at = models.DateTimeField(null=True, blank=True, db_index=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        abstract = True

