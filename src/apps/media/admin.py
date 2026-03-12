from django.contrib import admin
from django.utils import timezone

from .models import VideoEmbed


@admin.action(description="Approve selected videos")
def approve_videos(modeladmin, request, queryset):
    queryset.update(is_approved=True, approved_at=timezone.now(), approved_by=request.user)


@admin.action(description="Unapprove selected videos")
def unapprove_videos(modeladmin, request, queryset):
    queryset.update(is_approved=False, approved_at=None, approved_by=None)


@admin.register(VideoEmbed)
class VideoEmbedAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "provider_video_id",
        "person",
        "candidacy",
        "is_approved",
        "review_status",
        "updated_at",
    )
    list_filter = ("provider", "is_approved", "review_status")
    search_fields = ("provider_video_id", "title", "person__first_name", "person__last_name")
    readonly_fields = ("public_id", "created_at", "updated_at", "approved_at", "approved_by")
    autocomplete_fields = ("person", "candidacy")
    actions = [approve_videos, unapprove_videos]

    fieldsets = (
        ("Video", {"fields": ("public_id", "provider", "provider_video_id", "source_url", "title", "thumbnail_url", "published_at")}),
        ("Attach to", {"fields": ("person", "candidacy")}),
        ("Approval", {"fields": ("is_approved", "approved_at", "approved_by")}),
        ("Review", {"fields": ("review_status", "last_verified_at", "review_notes")}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )

