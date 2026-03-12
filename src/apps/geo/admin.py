from django.contrib import admin

from .models import District, Jurisdiction


@admin.register(Jurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "jurisdiction_type",
        "state",
        "county",
        "city",
        "review_status",
        "updated_at",
        "last_verified_at",
    )
    list_filter = ("jurisdiction_type", "state", "review_status")
    search_fields = ("name", "county", "city", "state", "fips_code")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("parent",)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "number",
        "district_type",
        "jurisdiction",
        "review_status",
        "updated_at",
        "last_verified_at",
    )
    list_filter = ("district_type", "jurisdiction__state", "review_status")
    search_fields = ("name", "number", "jurisdiction__name", "jurisdiction__state")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("jurisdiction",)

