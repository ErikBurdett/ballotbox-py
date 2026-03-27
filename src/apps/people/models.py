from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from urllib.parse import urlparse

from apps.core.models import PublicIdModel, ReviewableModel


class Party(models.TextChoices):
    DEMOCRATIC = "democratic", "Democratic"
    REPUBLICAN = "republican", "Republican"
    INDEPENDENT = "independent", "Independent"
    LIBERTARIAN = "libertarian", "Libertarian"
    GREEN = "green", "Green"
    NONPARTISAN = "nonpartisan", "Nonpartisan"
    OTHER = "other", "Other"
    UNKNOWN = "unknown", "Unknown"


class Person(PublicIdModel, ReviewableModel):
    first_name = models.CharField(max_length=128, blank=True, db_index=True)
    middle_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True, db_index=True)
    suffix = models.CharField(max_length=64, blank=True)
    preferred_name = models.CharField(max_length=128, blank=True)

    party = models.CharField(max_length=64, choices=Party.choices, default=Party.UNKNOWN, db_index=True)
    party_other = models.CharField(max_length=128, blank=True)

    photo_url = models.URLField(blank=True)

    manual_display_name = models.CharField(max_length=255, blank=True)
    manual_party = models.CharField(max_length=128, blank=True)
    manual_photo_url = models.URLField(blank=True)

    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        indexes = [
            GinIndex(fields=["search_vector"], name="person_search_vector_gin"),
            GinIndex(
                name="person_last_name_trgm_gin",
                fields=["last_name"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                name="person_first_name_trgm_gin",
                fields=["first_name"],
                opclasses=["gin_trgm_ops"],
            ),
        ]

    @property
    def display_name(self) -> str:
        if self.manual_display_name:
            return self.manual_display_name
        preferred = self.preferred_name or self.first_name
        parts = [preferred, self.middle_name, self.last_name, self.suffix]
        return " ".join([p for p in parts if p]).strip() or "Unknown"

    @property
    def display_party(self) -> str:
        if self.manual_party:
            return self.manual_party
        if self.party == Party.OTHER and self.party_other:
            return self.party_other
        return self.get_party_display()

    @property
    def display_photo_url(self) -> str:
        if self.manual_photo_url:
            return self.manual_photo_url
        u = (self.photo_url or "").strip()
        ul = u.lower()
        if not u:
            return ""
        # Hide provider placeholders (keeps UI clean; staff can override with manual_photo_url).
        try:
            path = (urlparse(u).path or "").lower()
        except Exception:
            path = ""
        if path.endswith(".svg"):
            return ""
        if "submitphoto" in ul:
            return ""
        if "bp-logo" in ul or "ballotpedia-logo" in ul:
            return ""
        if "flag_of_" in ul:
            return ""
        return u

    def __str__(self) -> str:
        return self.display_name


class ContactType(models.TextChoices):
    EMAIL = "email", "Email"
    PHONE = "phone", "Phone"
    WEBSITE = "website", "Website"
    ADDRESS = "address", "Address"


class ContactMethod(PublicIdModel, ReviewableModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="contact_methods")
    contact_type = models.CharField(max_length=32, choices=ContactType.choices, db_index=True)
    label = models.CharField(max_length=128, blank=True)
    value = models.TextField()
    is_public = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["person", "contact_type"])]

    def __str__(self) -> str:
        label = self.label or self.get_contact_type_display()
        return f"{self.person}: {label}"


class ExternalLinkKind(models.TextChoices):
    BALLOTPEDIA = "ballotpedia", "Ballotpedia"
    WIKIPEDIA = "wikipedia", "Wikipedia"
    OFFICIAL_SITE = "official_site", "Official site"
    OTHER = "other", "Other"


class ExternalLink(PublicIdModel, ReviewableModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="external_links")
    kind = models.CharField(max_length=32, choices=ExternalLinkKind.choices, default=ExternalLinkKind.OTHER)
    label = models.CharField(max_length=128, blank=True)
    url = models.URLField()

    class Meta:
        indexes = [models.Index(fields=["person", "kind"])]

    def __str__(self) -> str:
        return f"{self.person}: {self.url}"


class SocialPlatform(models.TextChoices):
    X = "x", "X"
    TWITTER = "twitter", "Twitter"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    YOUTUBE = "youtube", "YouTube"
    TIKTOK = "tiktok", "TikTok"
    LINKEDIN = "linkedin", "LinkedIn"
    OTHER = "other", "Other"


class SocialLink(PublicIdModel, ReviewableModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="social_links")
    platform = models.CharField(max_length=32, choices=SocialPlatform.choices, db_index=True)
    handle = models.CharField(max_length=128, blank=True)
    url = models.URLField()

    class Meta:
        indexes = [models.Index(fields=["person", "platform"])]

    def __str__(self) -> str:
        return f"{self.person}: {self.platform}"

