import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("elections", "0001_initial"),
        ("people", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VideoEmbed",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("provider", models.CharField(choices=[("youtube", "YouTube")], db_index=True, max_length=32)),
                ("provider_video_id", models.CharField(db_index=True, max_length=255)),
                ("source_url", models.URLField(blank=True)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("thumbnail_url", models.URLField(blank=True)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("is_approved", models.BooleanField(db_index=True, default=False)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_videos", to=settings.AUTH_USER_MODEL)),
                ("candidacy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="videos", to="elections.candidacy")),
                ("person", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="videos", to="people.person")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["provider", "provider_video_id"], name="media_video_provider_f6c1c4_idx"),
                    models.Index(fields=["is_approved"], name="media_video_is_appr_9b0bd1_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("provider", "provider_video_id"), name="uniq_video_provider_id")
                ],
            },
        ),
    ]

