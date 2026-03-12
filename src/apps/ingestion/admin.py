from __future__ import annotations

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import MergeReview, SourceRecord, SyncRun


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("provider", "status", "started_at", "finished_at", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("provider", "error_text")
    readonly_fields = ("public_id", "created_at", "updated_at", "started_at", "finished_at")


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ("provider", "external_id", "fetched_at", "normalized_link", "sync_run")
    list_filter = ("provider",)
    search_fields = ("external_id", "source_url", "source_name")
    readonly_fields = ("public_id", "created_at", "updated_at", "payload_sha256")
    autocomplete_fields = ("sync_run",)
    raw_id_fields = ("normalized_content_type",)

    def normalized_link(self, obj: SourceRecord):
        if not obj.normalized_content_type_id or not obj.normalized_object_id:
            return "—"
        ct = obj.normalized_content_type
        try:
            url = reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.normalized_object_id])
        except Exception:
            return f"{ct.app_label}.{ct.model} #{obj.normalized_object_id}"
        return format_html('<a href="{}">{} #{}</a>', url, ct.model, obj.normalized_object_id)

    normalized_link.short_description = "Normalized object"


@admin.register(MergeReview)
class MergeReviewAdmin(admin.ModelAdmin):
    list_display = ("status", "candidate_a_label", "candidate_b_label", "reviewer", "created_at")
    list_filter = ("status",)
    search_fields = ("merge_reason", "resolution_note")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("reviewer",)
    raw_id_fields = ("candidate_a_content_type", "candidate_b_content_type")

    def _candidate_label(self, ct, object_id):
        if not ct or not object_id:
            return "—"
        try:
            url = reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[object_id])
            return format_html('<a href="{}">{} #{}</a>', url, ct.model, object_id)
        except Exception:
            return f"{ct.app_label}.{ct.model} #{object_id}"

    def candidate_a_label(self, obj: MergeReview):
        return self._candidate_label(obj.candidate_a_content_type, obj.candidate_a_object_id)

    def candidate_b_label(self, obj: MergeReview):
        return self._candidate_label(obj.candidate_b_content_type, obj.candidate_b_object_id)

    candidate_a_label.short_description = "Candidate A"
    candidate_b_label.short_description = "Candidate B"

