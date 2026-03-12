import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("search", "0001_postgres_extensions")]

    operations = [
        migrations.CreateModel(
            name="Person",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("first_name", models.CharField(blank=True, db_index=True, max_length=128)),
                ("middle_name", models.CharField(blank=True, max_length=128)),
                ("last_name", models.CharField(blank=True, db_index=True, max_length=128)),
                ("suffix", models.CharField(blank=True, max_length=64)),
                ("preferred_name", models.CharField(blank=True, max_length=128)),
                ("party", models.CharField(choices=[("democratic", "Democratic"), ("republican", "Republican"), ("independent", "Independent"), ("libertarian", "Libertarian"), ("green", "Green"), ("nonpartisan", "Nonpartisan"), ("other", "Other"), ("unknown", "Unknown")], db_index=True, default="unknown", max_length=64)),
                ("party_other", models.CharField(blank=True, max_length=128)),
                ("photo_url", models.URLField(blank=True)),
                ("manual_display_name", models.CharField(blank=True, max_length=255)),
                ("manual_party", models.CharField(blank=True, max_length=128)),
                ("manual_photo_url", models.URLField(blank=True)),
                ("search_vector", SearchVectorField(editable=False, null=True)),
            ],
            options={
                "indexes": [
                    GinIndex(fields=["search_vector"], name="person_search_vector_gin"),
                    GinIndex(fields=["last_name"], name="person_last_name_trgm_gin", opclasses=["gin_trgm_ops"]),
                    GinIndex(fields=["first_name"], name="person_first_name_trgm_gin", opclasses=["gin_trgm_ops"]),
                ]
            },
        ),
        migrations.CreateModel(
            name="ContactMethod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("contact_type", models.CharField(choices=[("email", "Email"), ("phone", "Phone"), ("website", "Website"), ("address", "Address")], db_index=True, max_length=32)),
                ("label", models.CharField(blank=True, max_length=128)),
                ("value", models.TextField()),
                ("is_public", models.BooleanField(db_index=True, default=True)),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_methods", to="people.person")),
            ],
        ),
        migrations.CreateModel(
            name="ExternalLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("kind", models.CharField(choices=[("ballotpedia", "Ballotpedia"), ("wikipedia", "Wikipedia"), ("official_site", "Official site"), ("other", "Other")], default="other", max_length=32)),
                ("label", models.CharField(blank=True, max_length=128)),
                ("url", models.URLField()),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_links", to="people.person")),
            ],
        ),
        migrations.CreateModel(
            name="SocialLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("platform", models.CharField(choices=[("x", "X"), ("twitter", "Twitter"), ("facebook", "Facebook"), ("instagram", "Instagram"), ("youtube", "YouTube"), ("tiktok", "TikTok"), ("linkedin", "LinkedIn"), ("other", "Other")], db_index=True, max_length=32)),
                ("handle", models.CharField(blank=True, max_length=128)),
                ("url", models.URLField()),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_links", to="people.person")),
            ],
        ),
        migrations.AddIndex(
            model_name="contactmethod",
            index=models.Index(fields=["person", "contact_type"], name="people_cont_person_i_b20c1c_idx"),
        ),
        migrations.AddIndex(
            model_name="externallink",
            index=models.Index(fields=["person", "kind"], name="people_exte_person_i_24a4fe_idx"),
        ),
        migrations.AddIndex(
            model_name="sociallink",
            index=models.Index(fields=["person", "platform"], name="people_soci_person_i_965c54_idx"),
        ),
    ]

