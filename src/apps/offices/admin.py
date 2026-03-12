from django.contrib import admin

from .models import Office


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "branch", "jurisdiction", "is_partisan", "review_status", "updated_at")
    list_filter = ("level", "branch", "is_partisan", "review_status", "jurisdiction__state")
    search_fields = ("name", "jurisdiction__name", "description")
    readonly_fields = ("public_id", "created_at", "updated_at", "search_vector")
    autocomplete_fields = ("jurisdiction", "default_district")

    fieldsets = (
        ("Office", {"fields": ("public_id", "name", "level", "branch", "is_partisan")}),
        ("Geography", {"fields": ("jurisdiction", "district_type", "default_district")}),
        ("Details", {"fields": ("description",)}),
        ("Review", {"fields": ("review_status", "last_verified_at", "review_notes")}),
        ("Search", {"fields": ("search_vector",)}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )

