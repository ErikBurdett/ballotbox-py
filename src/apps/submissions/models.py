from __future__ import annotations

from django.db import models

from apps.core.models import TimeStampedModel
from apps.people.models import Party, Person


class ProfileRole(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    OFFICIAL = "official", "Official"


class SubmissionStatus(models.TextChoices):
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ProfileSubmission(TimeStampedModel):
    """Public proposal for a person profile; staff reviews before data is merged into the directory."""

    status = models.CharField(
        max_length=16,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING,
        db_index=True,
    )
    profile_role = models.CharField(max_length=16, choices=ProfileRole.choices, db_index=True)

    submitter_name = models.CharField(max_length=255, blank=True)
    submitter_email = models.EmailField()

    first_name = models.CharField(max_length=128, blank=True)
    middle_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    suffix = models.CharField(max_length=64, blank=True)
    preferred_name = models.CharField(max_length=128, blank=True)

    party = models.CharField(max_length=64, choices=Party.choices, default=Party.UNKNOWN)
    party_other = models.CharField(max_length=128, blank=True)

    photo_url = models.URLField(blank=True)
    manual_display_name = models.CharField(max_length=255, blank=True)
    manual_party = models.CharField(max_length=128, blank=True)
    manual_photo_url = models.URLField(blank=True)

    office_name = models.CharField(max_length=255, blank=True)
    jurisdiction_name = models.CharField(max_length=255, blank=True)
    district_name = models.CharField(max_length=255, blank=True)
    election_date = models.DateField(null=True, blank=True)
    race_or_role_notes = models.TextField(blank=True)

    contact_email = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=128, blank=True)
    contact_website = models.URLField(blank=True)

    link_ballotpedia = models.URLField(blank=True)
    link_wikipedia = models.URLField(blank=True)
    link_official_site = models.URLField(blank=True)

    social_x = models.URLField(blank=True)
    social_facebook = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)

    video_interview_url = models.URLField(blank=True)
    additional_notes = models.TextField(blank=True)

    reviewed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    review_notes = models.TextField(blank=True)
    created_person = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile_submissions",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="submissions_ps_status_cre_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_profile_role_display()}: {self.display_submitted_name()} ({self.get_status_display()})"

    def display_submitted_name(self) -> str:
        if self.manual_display_name.strip():
            return self.manual_display_name.strip()
        preferred = self.preferred_name or self.first_name
        parts = [preferred, self.middle_name, self.last_name, self.suffix]
        return " ".join([p for p in parts if p]).strip() or "Unknown"

    display_submitted_name.short_description = "Submitted name"  # type: ignore[attr-defined]
