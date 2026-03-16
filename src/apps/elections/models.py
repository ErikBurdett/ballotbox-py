from __future__ import annotations

from django.db import models

from apps.core.models import PublicIdModel, ReviewableModel
from apps.geo.models import District, Jurisdiction
from apps.offices.models import Office
from apps.people.models import Party, Person


class ElectionType(models.TextChoices):
    PRIMARY = "primary", "Primary"
    GENERAL = "general", "General"
    SPECIAL = "special", "Special"
    RUNOFF = "runoff", "Runoff"
    OTHER = "other", "Other"


class Election(PublicIdModel, ReviewableModel):
    name = models.CharField(max_length=255, db_index=True)
    election_type = models.CharField(max_length=32, choices=ElectionType.choices, default=ElectionType.GENERAL)
    date = models.DateField(db_index=True)
    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.PROTECT, related_name="elections")

    class Meta:
        indexes = [models.Index(fields=["date", "election_type"])]
        constraints = [
            models.UniqueConstraint(fields=["jurisdiction", "date", "election_type"], name="uniq_election_key")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.date})"


class Race(PublicIdModel, ReviewableModel):
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="races")
    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="races")
    district = models.ForeignKey(District, null=True, blank=True, on_delete=models.SET_NULL, related_name="races")

    seat_name = models.CharField(max_length=255, blank=True)
    is_partisan = models.BooleanField(default=False, db_index=True)

    # Democracy Works contest metadata (best-effort; may be blank for some contests/providers).
    contest_type = models.CharField(max_length=64, blank=True, db_index=True)
    seats_up_for_election = models.PositiveSmallIntegerField(null=True, blank=True)
    ranked_choice = models.BooleanField(default=False, db_index=True)
    ranked_choice_rank_number = models.PositiveSmallIntegerField(null=True, blank=True)
    has_primary = models.BooleanField(default=False, db_index=True)
    primary_date = models.DateField(null=True, blank=True, db_index=True)
    general_date = models.DateField(null=True, blank=True, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    about_office = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["election", "office"]),
            models.Index(fields=["office", "district"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["election", "office", "district", "seat_name"], name="uniq_race_key"
            )
        ]

    def __str__(self) -> str:
        district = f" · {self.district}" if self.district_id else ""
        seat = f" · {self.seat_name}" if self.seat_name else ""
        return f"{self.office}{district}{seat} ({self.election.date})"


class CandidacyStatus(models.TextChoices):
    DECLARED = "declared", "Declared"
    RUNNING = "running", "Running"
    WITHDREW = "withdrew", "Withdrew"
    DISQUALIFIED = "disqualified", "Disqualified"
    WON = "won", "Won"
    LOST = "lost", "Lost"
    UNKNOWN = "unknown", "Unknown"


class Candidacy(PublicIdModel, ReviewableModel):
    race = models.ForeignKey(Race, on_delete=models.PROTECT, related_name="candidacies")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="candidacies")

    party = models.CharField(max_length=64, choices=Party.choices, default=Party.UNKNOWN, db_index=True)
    party_other = models.CharField(max_length=128, blank=True)

    status = models.CharField(max_length=32, choices=CandidacyStatus.choices, default=CandidacyStatus.RUNNING)
    is_incumbent = models.BooleanField(default=False, db_index=True)
    is_challenger = models.BooleanField(default=False, db_index=True)

    # Democracy Works candidate metadata (best-effort).
    is_write_in = models.BooleanField(default=False, db_index=True)
    endorsement_count = models.PositiveSmallIntegerField(null=True, blank=True)
    running_mate_full_name = models.CharField(max_length=255, blank=True)
    running_mate_title = models.CharField(max_length=255, blank=True)
    ranked_choice_voting_round = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["party", "status"]),
            models.Index(fields=["race", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["race", "person"], name="uniq_candidacy_key"),
        ]

    @property
    def display_party(self) -> str:
        if self.party == Party.OTHER and self.party_other:
            return self.party_other
        return self.get_party_display()

    def __str__(self) -> str:
        return f"{self.person} for {self.race}"


class TermStatus(models.TextChoices):
    CURRENT = "current", "Current"
    FORMER = "former", "Former"
    UNKNOWN = "unknown", "Unknown"


class OfficeholderTerm(PublicIdModel, ReviewableModel):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="officeholder_terms")
    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="officeholder_terms")

    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.PROTECT, related_name="officeholder_terms")
    district = models.ForeignKey(District, null=True, blank=True, on_delete=models.SET_NULL, related_name="terms")

    party = models.CharField(max_length=64, choices=Party.choices, default=Party.UNKNOWN, db_index=True)
    party_other = models.CharField(max_length=128, blank=True)

    start_date = models.DateField(null=True, blank=True, db_index=True)
    end_date = models.DateField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=32, choices=TermStatus.choices, default=TermStatus.UNKNOWN, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["office", "status"]),
            models.Index(fields=["person", "status"]),
            models.Index(fields=["jurisdiction", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["person", "office", "start_date", "end_date"],
                name="uniq_officeholder_term_key",
            )
        ]

    @property
    def display_party(self) -> str:
        if self.party == Party.OTHER and self.party_other:
            return self.party_other
        return self.get_party_display()

    @property
    def is_current(self) -> bool:
        return self.status == TermStatus.CURRENT or self.end_date is None

    def __str__(self) -> str:
        return f"{self.person} · {self.office}"

