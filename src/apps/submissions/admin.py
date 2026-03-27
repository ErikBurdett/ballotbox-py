from django.contrib import admin

from .models import ProfileSubmission


@admin.register(ProfileSubmission)
class ProfileSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "profile_role",
        "display_submitted_name",
        "submitter_email",
        "office_name",
        "created_at",
        "reviewed_at",
        "created_person",
    )
    list_filter = ("status", "profile_role", "created_at")
    search_fields = (
        "submitter_email",
        "submitter_name",
        "first_name",
        "last_name",
        "manual_display_name",
        "office_name",
        "jurisdiction_name",
    )
    readonly_fields = ("created_at", "updated_at", "reviewed_at", "created_person")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Workflow", {"fields": ("status", "reviewed_at", "review_notes", "created_person")}),
        ("Submitter", {"fields": ("submitter_name", "submitter_email")}),
        ("Role", {"fields": ("profile_role", "office_name", "jurisdiction_name", "district_name", "election_date", "race_or_role_notes")}),
        ("Name & party", {"fields": ("first_name", "middle_name", "last_name", "suffix", "preferred_name", "party", "party_other")}),
        ("Display overrides", {"fields": ("manual_display_name", "manual_party", "manual_photo_url", "photo_url")}),
        ("Contact", {"fields": ("contact_email", "contact_phone", "contact_website")}),
        ("Links", {"fields": ("link_ballotpedia", "link_wikipedia", "link_official_site")}),
        ("Social", {"fields": ("social_x", "social_facebook", "social_instagram", "social_youtube", "social_tiktok", "social_linkedin")}),
        ("Media & notes", {"fields": ("video_interview_url", "additional_notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
