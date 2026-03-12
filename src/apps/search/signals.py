from __future__ import annotations

from django.contrib.postgres.search import SearchVector
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.offices.models import Office
from apps.people.models import Person


@receiver(post_save, sender=Person)
def update_person_search_vector(sender, instance: Person, **kwargs):
    Person.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector("preferred_name", "first_name", "last_name", config="english")
    )


@receiver(post_save, sender=Office)
def update_office_search_vector(sender, instance: Office, **kwargs):
    Office.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector("name", "description", config="english")
    )

