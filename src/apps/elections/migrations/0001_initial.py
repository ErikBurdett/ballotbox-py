import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("geo", "0001_initial"),
        ("offices", "0001_initial"),
        ("people", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Election",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(db_index=True, max_length=255)),
                ("election_type", models.CharField(choices=[("primary", "Primary"), ("general", "General"), ("special", "Special"), ("runoff", "Runoff"), ("other", "Other")], default="general", max_length=32)),
                ("date", models.DateField(db_index=True)),
                ("jurisdiction", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="elections", to="geo.jurisdiction")),
            ],
            options={
                "indexes": [models.Index(fields=["date", "election_type"], name="elections_el_date_987c93_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("jurisdiction", "date", "election_type"), name="uniq_election_key")
                ],
            },
        ),
        migrations.CreateModel(
            name="Race",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("seat_name", models.CharField(blank=True, max_length=255)),
                ("is_partisan", models.BooleanField(db_index=True, default=False)),
                ("district", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="races", to="geo.district")),
                ("election", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="races", to="elections.election")),
                ("office", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="races", to="offices.office")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["election", "office"], name="elections_ra_electio_1a5b8a_idx"),
                    models.Index(fields=["office", "district"], name="elections_ra_office__eb6597_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("election", "office", "district", "seat_name"), name="uniq_race_key")
                ],
            },
        ),
        migrations.CreateModel(
            name="Candidacy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("party", models.CharField(choices=[("democratic", "Democratic"), ("republican", "Republican"), ("independent", "Independent"), ("libertarian", "Libertarian"), ("green", "Green"), ("nonpartisan", "Nonpartisan"), ("other", "Other"), ("unknown", "Unknown")], db_index=True, default="unknown", max_length=64)),
                ("party_other", models.CharField(blank=True, max_length=128)),
                ("status", models.CharField(choices=[("declared", "Declared"), ("running", "Running"), ("withdrew", "Withdrew"), ("disqualified", "Disqualified"), ("won", "Won"), ("lost", "Lost"), ("unknown", "Unknown")], default="running", max_length=32)),
                ("is_incumbent", models.BooleanField(db_index=True, default=False)),
                ("is_challenger", models.BooleanField(db_index=True, default=False)),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="candidacies", to="people.person")),
                ("race", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="candidacies", to="elections.race")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["party", "status"], name="elections_ca_party_s_8a4d25_idx"),
                    models.Index(fields=["race", "status"], name="elections_ca_race_s_b3e8dc_idx"),
                ],
                "constraints": [models.UniqueConstraint(fields=("race", "person"), name="uniq_candidacy_key")],
            },
        ),
        migrations.CreateModel(
            name="OfficeholderTerm",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("review_status", models.CharField(choices=[("draft", "Draft"), ("needs_review", "Needs review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="needs_review", max_length=32)),
                ("last_verified_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("party", models.CharField(choices=[("democratic", "Democratic"), ("republican", "Republican"), ("independent", "Independent"), ("libertarian", "Libertarian"), ("green", "Green"), ("nonpartisan", "Nonpartisan"), ("other", "Other"), ("unknown", "Unknown")], db_index=True, default="unknown", max_length=64)),
                ("party_other", models.CharField(blank=True, max_length=128)),
                ("start_date", models.DateField(blank=True, db_index=True, null=True)),
                ("end_date", models.DateField(blank=True, db_index=True, null=True)),
                ("status", models.CharField(choices=[("current", "Current"), ("former", "Former"), ("unknown", "Unknown")], db_index=True, default="unknown", max_length=32)),
                ("district", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="terms", to="geo.district")),
                ("jurisdiction", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="officeholder_terms", to="geo.jurisdiction")),
                ("office", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="officeholder_terms", to="offices.office")),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="officeholder_terms", to="people.person")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["office", "status"], name="elections_of_office__a450db_idx"),
                    models.Index(fields=["person", "status"], name="elections_of_person__b6afdf_idx"),
                    models.Index(fields=["jurisdiction", "status"], name="elections_of_jurisdi_f43331_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("person", "office", "start_date", "end_date"), name="uniq_officeholder_term_key")
                ],
            },
        ),
    ]

