from django.contrib import admin

from .models import Candidacy, Election, OfficeholderTerm, Race


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "election_type", "jurisdiction", "review_status", "updated_at")
    list_filter = ("election_type", "date", "jurisdiction__state", "review_status")
    search_fields = ("name", "jurisdiction__name")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("jurisdiction",)


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ("office", "election", "district", "seat_name", "is_partisan", "review_status", "updated_at")
    list_filter = ("is_partisan", "election__date", "election__jurisdiction__state", "review_status")
    search_fields = ("office__name", "seat_name", "district__name", "district__number")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("election", "office", "district")


@admin.register(Candidacy)
class CandidacyAdmin(admin.ModelAdmin):
    list_display = ("person", "race", "party", "status", "is_incumbent", "is_challenger", "review_status", "updated_at")
    list_filter = ("party", "status", "is_incumbent", "is_challenger", "race__election__date", "review_status")
    search_fields = ("person__first_name", "person__last_name", "race__office__name")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("person", "race")


@admin.register(OfficeholderTerm)
class OfficeholderTermAdmin(admin.ModelAdmin):
    list_display = ("person", "office", "jurisdiction", "district", "party", "status", "start_date", "end_date", "updated_at")
    list_filter = ("status", "party", "jurisdiction__state", "office__level", "office__branch", "review_status")
    search_fields = ("person__first_name", "person__last_name", "office__name", "jurisdiction__name")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("person", "office", "jurisdiction", "district")

