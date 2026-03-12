import factory
from django.utils import timezone

from apps.elections.models import Candidacy, Election, OfficeholderTerm, Race, TermStatus
from apps.geo.models import District, DistrictType, Jurisdiction, JurisdictionType
from apps.offices.models import Office, OfficeBranch, OfficeLevel
from apps.people.models import Party, Person


class JurisdictionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Jurisdiction

    name = factory.Sequence(lambda n: f"Demo Jurisdiction {n}")
    jurisdiction_type = JurisdictionType.CITY
    state = "CA"
    county = "Demo County"
    city = factory.Sequence(lambda n: f"Demo City {n}")


class DistrictFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = District

    jurisdiction = factory.SubFactory(JurisdictionFactory)
    district_type = DistrictType.CITY_COUNCIL
    name = "Ward"
    number = factory.Sequence(lambda n: str(n + 1))


class OfficeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Office

    jurisdiction = factory.SubFactory(JurisdictionFactory)
    name = factory.Sequence(lambda n: f"Office {n}")
    level = OfficeLevel.LOCAL
    branch = OfficeBranch.EXECUTIVE
    is_partisan = False


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    first_name = factory.Sequence(lambda n: f"Alex{n}")
    last_name = factory.Sequence(lambda n: f"Rivera{n}")
    preferred_name = ""
    party = Party.UNKNOWN


class OfficeholderTermFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OfficeholderTerm

    person = factory.SubFactory(PersonFactory)
    office = factory.SubFactory(OfficeFactory)
    jurisdiction = factory.SelfAttribute("office.jurisdiction")
    district = None
    party = Party.UNKNOWN
    status = TermStatus.CURRENT
    start_date = timezone.now().date().replace(year=2024, month=1, day=1)
    end_date = None


class ElectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Election

    jurisdiction = factory.SubFactory(JurisdictionFactory)
    name = factory.Sequence(lambda n: f"Election {n}")
    election_type = "general"
    date = timezone.now().date().replace(year=2026, month=11, day=3)


class RaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Race

    election = factory.SubFactory(ElectionFactory)
    office = factory.SubFactory(OfficeFactory, jurisdiction=factory.SelfAttribute("..election.jurisdiction"))
    district = None
    seat_name = ""
    is_partisan = False


class CandidacyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Candidacy

    race = factory.SubFactory(RaceFactory)
    person = factory.SubFactory(PersonFactory)
    party = Party.UNKNOWN
    status = "running"
    is_incumbent = False
    is_challenger = True

