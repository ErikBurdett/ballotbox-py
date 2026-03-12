from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import PublicIdModel, ReviewableModel
from apps.elections.models import Candidacy
from apps.people.models import Person


class VideoProvider(models.TextChoices):
    YOUTUBE = "youtube", "YouTube"


ALLOWED_VIDEO_PROVIDERS = {VideoProvider.YOUTUBE}


class VideoEmbed(PublicIdModel, ReviewableModel):
    provider = models.CharField(max_length=32, choices=VideoProvider.choices, db_index=True)
    provider_video_id = models.CharField(max_length=255, db_index=True)
    source_url = models.URLField(blank=True)

    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name="videos")
    candidacy = models.ForeignKey(
        Candidacy, null=True, blank=True, on_delete=models.CASCADE, related_name="videos"
    )

    title = models.CharField(max_length=255, blank=True)
    thumbnail_url = models.URLField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    is_approved = models.BooleanField(default=False, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_videos"
    )

    class Meta:
        indexes = [models.Index(fields=["provider", "provider_video_id"]), models.Index(fields=["is_approved"])]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_video_id"], name="uniq_video_provider_id"
            )
        ]

    def clean(self):
        super().clean()
        if self.provider not in {p.value for p in ALLOWED_VIDEO_PROVIDERS}:
            raise ValidationError({"provider": "Video provider is not allowlisted."})

    @property
    def has_valid_provider(self) -> bool:
        return self.provider in {p.value for p in ALLOWED_VIDEO_PROVIDERS}

    @property
    def embed_url(self) -> str:
        if self.provider == VideoProvider.YOUTUBE:
            return f"https://www.youtube-nocookie.com/embed/{self.provider_video_id}"
        return ""

    def __str__(self) -> str:
        target = self.person or self.candidacy
        return f"{self.get_provider_display()} video for {target}"


def is_safe_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.netloc or "").lower()
    return host in {"www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com"}

