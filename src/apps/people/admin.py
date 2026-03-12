from django.contrib import admin

from .models import ContactMethod, ExternalLink, Person, SocialLink


class ContactMethodInline(admin.TabularInline):
    model = ContactMethod
    extra = 0


class ExternalLinkInline(admin.TabularInline):
    model = ExternalLink
    extra = 0


class SocialLinkInline(admin.TabularInline):
    model = SocialLink
    extra = 0


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("display_name", "party", "review_status", "updated_at", "last_verified_at")
    list_filter = ("party", "review_status")
    search_fields = ("first_name", "last_name", "preferred_name", "manual_display_name", "party_other")
    readonly_fields = ("public_id", "created_at", "updated_at")
    inlines = [ContactMethodInline, ExternalLinkInline, SocialLinkInline]

    fieldsets = (
        ("Identity", {"fields": ("public_id", "first_name", "preferred_name", "middle_name", "last_name", "suffix")}),
        ("Party & photo", {"fields": ("party", "party_other", "photo_url")}),
        ("Manual overrides", {"fields": ("manual_display_name", "manual_party", "manual_photo_url")}),
        ("Review", {"fields": ("review_status", "last_verified_at", "review_notes")}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ContactMethod)
class ContactMethodAdmin(admin.ModelAdmin):
    list_display = ("person", "contact_type", "label", "is_public", "review_status", "updated_at")
    list_filter = ("contact_type", "is_public", "review_status")
    search_fields = ("person__first_name", "person__last_name", "value", "label")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("person",)


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("person", "kind", "url", "review_status", "updated_at")
    list_filter = ("kind", "review_status")
    search_fields = ("person__first_name", "person__last_name", "url", "label")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("person",)


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ("person", "platform", "handle", "url", "review_status", "updated_at")
    list_filter = ("platform", "review_status")
    search_fields = ("person__first_name", "person__last_name", "handle", "url")
    readonly_fields = ("public_id", "created_at", "updated_at")
    autocomplete_fields = ("person",)

