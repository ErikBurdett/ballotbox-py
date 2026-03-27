from __future__ import annotations

from django import forms

from apps.people.models import Party

from .models import ProfileSubmission
from .utils import extract_youtube_video_id


class ProfileSubmissionForm(forms.ModelForm):
    class Meta:
        model = ProfileSubmission
        fields = [
            "profile_role",
            "submitter_name",
            "submitter_email",
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "preferred_name",
            "party",
            "party_other",
            "photo_url",
            "manual_display_name",
            "manual_party",
            "manual_photo_url",
            "office_name",
            "jurisdiction_name",
            "district_name",
            "election_date",
            "race_or_role_notes",
            "contact_email",
            "contact_phone",
            "contact_website",
            "link_ballotpedia",
            "link_wikipedia",
            "link_official_site",
            "social_x",
            "social_facebook",
            "social_instagram",
            "social_youtube",
            "social_tiktok",
            "social_linkedin",
            "video_interview_url",
            "additional_notes",
        ]
        widgets = {
            "profile_role": forms.Select(attrs={"class": "select"}),
            "submitter_name": forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
            "submitter_email": forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
            "first_name": forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}),
            "middle_name": forms.TextInput(attrs={"class": "input", "autocomplete": "additional-name"}),
            "last_name": forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}),
            "suffix": forms.TextInput(attrs={"class": "input"}),
            "preferred_name": forms.TextInput(attrs={"class": "input"}),
            "party": forms.Select(attrs={"class": "select"}),
            "party_other": forms.TextInput(attrs={"class": "input"}),
            "photo_url": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "manual_display_name": forms.TextInput(attrs={"class": "input"}),
            "manual_party": forms.TextInput(attrs={"class": "input"}),
            "manual_photo_url": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "office_name": forms.TextInput(attrs={"class": "input"}),
            "jurisdiction_name": forms.TextInput(attrs={"class": "input"}),
            "district_name": forms.TextInput(attrs={"class": "input"}),
            "election_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "race_or_role_notes": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "contact_email": forms.TextInput(attrs={"class": "input"}),
            "contact_phone": forms.TextInput(attrs={"class": "input", "autocomplete": "tel"}),
            "contact_website": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "link_ballotpedia": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "link_wikipedia": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "link_official_site": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_x": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_facebook": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_instagram": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_youtube": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_tiktok": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "social_linkedin": forms.URLInput(attrs={"class": "input", "placeholder": "https://"}),
            "video_interview_url": forms.URLInput(attrs={"class": "input", "placeholder": "YouTube watch or youtu.be URL"}),
            "additional_notes": forms.Textarea(attrs={"class": "input", "rows": 5}),
        }

    def clean(self):
        data = super().clean()
        party = data.get("party")
        party_other = (data.get("party_other") or "").strip()

        if party == Party.OTHER and not party_other:
            self.add_error("party_other", "Please specify the party when you select “Other”.")
        video = (data.get("video_interview_url") or "").strip()
        if video and not extract_youtube_video_id(video):
            self.add_error(
                "video_interview_url",
                "Use a full YouTube link (youtube.com or youtu.be). Other hosts are not accepted yet.",
            )
        return data


class StaffLoginForm(forms.Form):
    access_code = forms.CharField(
        label="Access code",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "current-password"}),
    )


class ReviewNotesForm(forms.Form):
    review_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Optional notes for the record"}),
    )
