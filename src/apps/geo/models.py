from __future__ import annotations

from django.contrib.gis.db import models
from django.utils.text import slugify

from apps.core.models import PublicIdModel, ReviewableModel


class JurisdictionType(models.TextChoices):
    STATE = "state", "State"
    COUNTY = "county", "County"
    CITY = "city", "City"
    TOWN = "town", "Town"
    TOWNSHIP = "township", "Township"
    VILLAGE = "village", "Village"
    BOROUGH = "borough", "Borough"
    TRIBAL = "tribal", "Tribal"
    SPECIAL_DISTRICT = "special_district", "Special district"
    SCHOOL_DISTRICT = "school_district", "School district"
    OTHER = "other", "Other"


class DistrictType(models.TextChoices):
    CONGRESSIONAL = "congressional", "Congressional"
    STATE_SENATE = "state_senate", "State senate"
    STATE_HOUSE = "state_house", "State house"
    COUNTY = "county", "County"
    CITY_COUNCIL = "city_council", "City council"
    SCHOOL_BOARD = "school_board", "School board"
    JUDICIAL = "judicial", "Judicial"
    PRECINCT = "precinct", "Precinct"
    OTHER = "other", "Other"


class Jurisdiction(PublicIdModel, ReviewableModel):
    name = models.CharField(max_length=255, db_index=True)
    jurisdiction_type = models.CharField(max_length=64, choices=JurisdictionType.choices, db_index=True)

    state = models.CharField(max_length=2, db_index=True)
    county = models.CharField(max_length=255, blank=True, db_index=True)
    city = models.CharField(max_length=255, blank=True, db_index=True)

    fips_code = models.CharField(max_length=16, blank=True, db_index=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="children", on_delete=models.SET_NULL
    )

    geom = models.MultiPolygonField(null=True, blank=True, srid=4326)

    class Meta:
        indexes = [
            models.Index(fields=["state", "jurisdiction_type"]),
            models.Index(fields=["state", "county", "city"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["state", "jurisdiction_type", "name", "county", "city"],
                name="uniq_jurisdiction_natural_key",
            )
        ]

    def __str__(self) -> str:
        parts = [self.name]
        if self.city:
            parts.append(self.city)
        if self.county:
            parts.append(self.county)
        parts.append(self.state)
        return " · ".join([p for p in parts if p])

    def url_slug(self) -> str:
        """Stable path segment for public county URLs (see ``geo:county_detail``)."""
        return slugify(self.name)


class District(PublicIdModel, ReviewableModel):
    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.PROTECT, related_name="districts")
    district_type = models.CharField(max_length=64, choices=DistrictType.choices, db_index=True)

    name = models.CharField(max_length=255, db_index=True)
    number = models.CharField(max_length=64, blank=True, db_index=True)

    geom = models.MultiPolygonField(null=True, blank=True, srid=4326)

    class Meta:
        indexes = [
            models.Index(fields=["district_type", "name"]),
            models.Index(fields=["jurisdiction", "district_type", "number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "district_type", "name", "number"],
                name="uniq_district_natural_key",
            )
        ]

    def __str__(self) -> str:
        label = self.name
        if self.number:
            label = f"{label} {self.number}"
        return f"{label} ({self.get_district_type_display()})"

