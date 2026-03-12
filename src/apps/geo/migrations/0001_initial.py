import uuid

from django.contrib.gis.db import models as gis_models
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Jurisdiction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(db_index=True, max_length=255)),
                ("jurisdiction_type", models.CharField(choices=[("state", "State"), ("county", "County"), ("city", "City"), ("town", "Town"), ("township", "Township"), ("village", "Village"), ("borough", "Borough"), ("tribal", "Tribal"), ("special_district", "Special district"), ("school_district", "School district"), ("other", "Other")], db_index=True, max_length=64)),
                ("state", models.CharField(db_index=True, max_length=2)),
                ("county", models.CharField(blank=True, db_index=True, max_length=255)),
                ("city", models.CharField(blank=True, db_index=True, max_length=255)),
                ("fips_code", models.CharField(blank=True, db_index=True, max_length=16)),
                ("geom", gis_models.MultiPolygonField(blank=True, null=True, srid=4326)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="children", to="geo.jurisdiction")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("state", "jurisdiction_type", "name", "county", "city"), name="uniq_jurisdiction_natural_key")
                ],
            },
        ),
        migrations.CreateModel(
            name="District",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("district_type", models.CharField(choices=[("congressional", "Congressional"), ("state_senate", "State senate"), ("state_house", "State house"), ("county", "County"), ("city_council", "City council"), ("school_board", "School board"), ("judicial", "Judicial"), ("precinct", "Precinct"), ("other", "Other")], db_index=True, max_length=64)),
                ("name", models.CharField(db_index=True, max_length=255)),
                ("number", models.CharField(blank=True, db_index=True, max_length=64)),
                ("geom", gis_models.MultiPolygonField(blank=True, null=True, srid=4326)),
                ("jurisdiction", models.ForeignKey(on_delete=models.PROTECT, related_name="districts", to="geo.jurisdiction")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("jurisdiction", "district_type", "name", "number"), name="uniq_district_natural_key")
                ],
            },
        ),
        migrations.AddIndex(
            model_name="jurisdiction",
            index=models.Index(fields=["state", "jurisdiction_type"], name="geo_jurisdi_state_64ab3f_idx"),
        ),
        migrations.AddIndex(
            model_name="jurisdiction",
            index=models.Index(fields=["state", "county", "city"], name="geo_jurisdi_state_1e1a7e_idx"),
        ),
        migrations.AddIndex(
            model_name="district",
            index=models.Index(fields=["district_type", "name"], name="geo_distri_distri_846743_idx"),
        ),
        migrations.AddIndex(
            model_name="district",
            index=models.Index(fields=["jurisdiction", "district_type", "number"], name="geo_distri_jurisdi_3c5cf5_idx"),
        ),
    ]

