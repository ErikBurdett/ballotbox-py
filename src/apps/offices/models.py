from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.core.models import PublicIdModel, ReviewableModel
from apps.geo.models import District, DistrictType, Jurisdiction


class OfficeLevel(models.TextChoices):
    FEDERAL = "federal", "Federal"
    STATE = "state", "State"
    COUNTY = "county", "County"
    LOCAL = "local", "Local"


class OfficeBranch(models.TextChoices):
    EXECUTIVE = "executive", "Executive"
    LEGISLATIVE = "legislative", "Legislative"
    JUDICIAL = "judicial", "Judicial"
    OTHER = "other", "Other"


class Office(PublicIdModel, ReviewableModel):
    name = models.CharField(max_length=255, db_index=True)
    level = models.CharField(max_length=32, choices=OfficeLevel.choices, db_index=True)
    branch = models.CharField(max_length=32, choices=OfficeBranch.choices, db_index=True)

    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.PROTECT, related_name="offices")
    district_type = models.CharField(
        max_length=64, choices=DistrictType.choices, blank=True, db_index=True
    )
    default_district = models.ForeignKey(
        District, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_for_offices"
    )

    description = models.TextField(blank=True)
    is_partisan = models.BooleanField(default=False, db_index=True)

    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        indexes = [
            GinIndex(fields=["search_vector"], name="office_search_vector_gin"),
            GinIndex(
                name="office_name_trgm_gin",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            ),
            models.Index(fields=["level", "branch"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "level", "branch", "jurisdiction"],
                name="uniq_office_natural_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.jurisdiction}"

