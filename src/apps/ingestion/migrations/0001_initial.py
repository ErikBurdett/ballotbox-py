import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("provider", models.CharField(choices=[("ballotready_civicengine", "BallotReady/CivicEngine"), ("ballotpedia", "Ballotpedia"), ("openstates", "OpenStates"), ("openfec", "OpenFEC"), ("youtube", "YouTube")], db_index=True, max_length=64)),
                ("status", models.CharField(choices=[("running", "Running"), ("success", "Success"), ("failed", "Failed"), ("partial", "Partial"), ("cancelled", "Cancelled")], db_index=True, default="running", max_length=32)),
                ("started_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("finished_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("stats", models.JSONField(blank=True, default=dict)),
                ("error_text", models.TextField(blank=True)),
            ],
            options={
                "indexes": [models.Index(fields=["provider", "started_at"], name="ingestion_sy_provider_8c2b16_idx")],
            },
        ),
        migrations.CreateModel(
            name="SourceRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("provider", models.CharField(choices=[("ballotready_civicengine", "BallotReady/CivicEngine"), ("ballotpedia", "Ballotpedia"), ("openstates", "OpenStates"), ("openfec", "OpenFEC"), ("youtube", "YouTube")], db_index=True, max_length=64)),
                ("external_id", models.CharField(db_index=True, max_length=255)),
                ("source_url", models.URLField(blank=True)),
                ("source_name", models.CharField(blank=True, max_length=255)),
                ("fetched_at", models.DateTimeField(db_index=True)),
                ("payload", models.JSONField()),
                ("payload_sha256", models.CharField(db_index=True, max_length=64)),
                ("normalized_object_id", models.PositiveBigIntegerField(blank=True, db_index=True, null=True)),
                ("normalized_content_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="contenttypes.contenttype")),
                ("sync_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="records", to="ingestion.syncrun")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["provider", "external_id"], name="ingestion_so_provider_57bdb5_idx"),
                    models.Index(fields=["payload_sha256"], name="ingestion_so_payload__a0bd07_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("provider", "external_id", "payload_sha256"), name="uniq_source_payload")
                ],
            },
        ),
        migrations.CreateModel(
            name="MergeReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("status", models.CharField(choices=[("open", "Open"), ("merged", "Merged"), ("rejected", "Rejected")], db_index=True, default="open", max_length=32)),
                ("candidate_a_object_id", models.PositiveBigIntegerField(db_index=True)),
                ("candidate_b_object_id", models.PositiveBigIntegerField(db_index=True)),
                ("merge_reason", models.TextField(blank=True)),
                ("resolution_note", models.TextField(blank=True)),
                ("candidate_a_content_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="contenttypes.contenttype")),
                ("candidate_b_content_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="contenttypes.contenttype")),
                ("reviewer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="merge_reviews", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["status", "created_at"], name="ingestion_me_status__7f7c70_idx")],
            },
        ),
    ]

