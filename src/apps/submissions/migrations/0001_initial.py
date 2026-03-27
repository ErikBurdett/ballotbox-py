import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("people", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfileSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "profile_role",
                    models.CharField(
                        choices=[("candidate", "Candidate"), ("official", "Official")],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("submitter_name", models.CharField(blank=True, max_length=255)),
                ("submitter_email", models.EmailField(max_length=254)),
                ("first_name", models.CharField(blank=True, max_length=128)),
                ("middle_name", models.CharField(blank=True, max_length=128)),
                ("last_name", models.CharField(blank=True, max_length=128)),
                ("suffix", models.CharField(blank=True, max_length=64)),
                ("preferred_name", models.CharField(blank=True, max_length=128)),
                (
                    "party",
                    models.CharField(
                        choices=[
                            ("democratic", "Democratic"),
                            ("republican", "Republican"),
                            ("independent", "Independent"),
                            ("libertarian", "Libertarian"),
                            ("green", "Green"),
                            ("nonpartisan", "Nonpartisan"),
                            ("other", "Other"),
                            ("unknown", "Unknown"),
                        ],
                        db_index=True,
                        default="unknown",
                        max_length=64,
                    ),
                ),
                ("party_other", models.CharField(blank=True, max_length=128)),
                ("photo_url", models.URLField(blank=True)),
                ("manual_display_name", models.CharField(blank=True, max_length=255)),
                ("manual_party", models.CharField(blank=True, max_length=128)),
                ("manual_photo_url", models.URLField(blank=True)),
                ("office_name", models.CharField(blank=True, max_length=255)),
                ("jurisdiction_name", models.CharField(blank=True, max_length=255)),
                ("district_name", models.CharField(blank=True, max_length=255)),
                ("election_date", models.DateField(blank=True, null=True)),
                ("race_or_role_notes", models.TextField(blank=True)),
                ("contact_email", models.CharField(blank=True, max_length=255)),
                ("contact_phone", models.CharField(blank=True, max_length=128)),
                ("contact_website", models.URLField(blank=True)),
                ("link_ballotpedia", models.URLField(blank=True)),
                ("link_wikipedia", models.URLField(blank=True)),
                ("link_official_site", models.URLField(blank=True)),
                ("social_x", models.URLField(blank=True)),
                ("social_facebook", models.URLField(blank=True)),
                ("social_instagram", models.URLField(blank=True)),
                ("social_youtube", models.URLField(blank=True)),
                ("social_tiktok", models.URLField(blank=True)),
                ("social_linkedin", models.URLField(blank=True)),
                ("video_interview_url", models.URLField(blank=True)),
                ("additional_notes", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                (
                    "created_person",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="profile_submissions",
                        to="people.person",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="profilesubmission",
            index=models.Index(fields=["status", "-created_at"], name="submissions_ps_status_cre_idx"),
        ),
    ]
