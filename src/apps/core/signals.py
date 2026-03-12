from __future__ import annotations

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ROLE_EDITOR = "editor"
ROLE_REVIEWER = "reviewer"


def _permission_codenames_for_models(app_labels: list[str]) -> set[str]:
    codenames: set[str] = set()
    for app_label in app_labels:
        app_config = apps.get_app_config(app_label)
        for model in app_config.get_models():
            opts = model._meta
            codenames.update(
                {
                    f"view_{opts.model_name}",
                    f"add_{opts.model_name}",
                    f"change_{opts.model_name}",
                }
            )
    return codenames


@receiver(post_migrate)
def ensure_staff_groups(sender, **kwargs):
    editor, _ = Group.objects.get_or_create(name=ROLE_EDITOR)
    reviewer, _ = Group.objects.get_or_create(name=ROLE_REVIEWER)

    editable_app_labels = ["geo", "people", "offices", "elections", "media"]
    ingestion_app_labels = ["ingestion"]

    editor_codenames = _permission_codenames_for_models(editable_app_labels)
    reviewer_codenames = _permission_codenames_for_models(editable_app_labels + ingestion_app_labels)

    editor.permissions.set(Permission.objects.filter(codename__in=editor_codenames))
    reviewer.permissions.set(Permission.objects.filter(codename__in=reviewer_codenames))

