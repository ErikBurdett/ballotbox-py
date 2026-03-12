import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("geo", "0001_initial"),
        ("search", "0001_postgres_extensions"),
    ]

    operations = [
        migrations.CreateModel(
            name="Office",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(db_index=True, max_length=255)),
                ("level", models.CharField(choices=[("federal", "Federal"), ("state", "State"), ("county", "County"), ("local", "Local")], db_index=True, max_length=32)),
                ("branch", models.CharField(choices=[("executive", "Executive"), ("legislative", "Legislative"), ("judicial", "Judicial"), ("other", "Other")], db_index=True, max_length=32)),
                ("district_type", models.CharField(blank=True, choices=[("congressional", "Congressional"), ("state_senate", "State senate"), ("state_house", "State house"), ("county", "County"), ("city_council", "City council"), ("school_board", "School board"), ("judicial", "Judicial"), ("precinct", "Precinct"), ("other", "Other")], db_index=True, max_length=64)),
                ("description", models.TextField(blank=True)),
                ("is_partisan", models.BooleanField(db_index=True, default=False)),
                ("search_vector", SearchVectorField(editable=False, null=True)),
                ("default_district", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="default_for_offices", to="geo.district")),
                ("jurisdiction", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="offices", to="geo.jurisdiction")),
            ],
            options={
                "indexes": [
                    GinIndex(fields=["search_vector"], name="office_search_vector_gin"),
                    GinIndex(fields=["name"], name="office_name_trgm_gin", opclasses=["gin_trgm_ops"]),
                    models.Index(fields=["level", "branch"], name="offices_off_level_ba926f_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("name", "level", "branch", "jurisdiction"), name="uniq_office_natural_key")
                ],
            },
        ),
    ]

