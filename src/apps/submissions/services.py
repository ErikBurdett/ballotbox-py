from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.models import ReviewStatus
from apps.media.models import VideoEmbed, VideoProvider
from apps.people.models import ContactMethod, ContactType, ExternalLink, ExternalLinkKind, Person, SocialLink, SocialPlatform

from .models import ProfileSubmission, SubmissionStatus
from .utils import extract_youtube_video_id


def _create_contact_if_value(person: Person, contact_type: str, value: str) -> None:
    v = value.strip()
    if not v:
        return
    ContactMethod.objects.create(
        person=person,
        contact_type=contact_type,
        label="",
        value=v,
        is_public=True,
        review_status=ReviewStatus.NEEDS_REVIEW,
    )


def _create_external_if_url(person: Person, kind: str, url: str) -> None:
    u = url.strip()
    if not u:
        return
    ExternalLink.objects.create(
        person=person,
        kind=kind,
        label="",
        url=u,
        review_status=ReviewStatus.NEEDS_REVIEW,
    )


def _create_social_if_url(person: Person, platform: str, url: str) -> None:
    u = url.strip()
    if not u:
        return
    SocialLink.objects.create(
        person=person,
        platform=platform,
        handle="",
        url=u,
        review_status=ReviewStatus.NEEDS_REVIEW,
    )


@transaction.atomic
def approve_submission(submission: ProfileSubmission, review_notes: str = "") -> Person:
    if submission.status != SubmissionStatus.PENDING:
        raise ValueError("Only pending submissions can be approved.")

    note_parts = [
        submission.race_or_role_notes.strip(),
        submission.additional_notes.strip(),
    ]
    combined_notes = "\n\n".join(p for p in note_parts if p)

    person = Person.objects.create(
        first_name=submission.first_name.strip(),
        middle_name=submission.middle_name.strip(),
        last_name=submission.last_name.strip(),
        suffix=submission.suffix.strip(),
        preferred_name=submission.preferred_name.strip(),
        party=submission.party,
        party_other=submission.party_other.strip(),
        photo_url=(submission.photo_url or "").strip(),
        manual_display_name=submission.manual_display_name.strip(),
        manual_party=submission.manual_party.strip(),
        manual_photo_url=(submission.manual_photo_url or "").strip(),
        review_status=ReviewStatus.NEEDS_REVIEW,
        review_notes=combined_notes[:8000] if combined_notes else "",
    )

    _create_contact_if_value(person, ContactType.EMAIL, submission.contact_email)
    _create_contact_if_value(person, ContactType.PHONE, submission.contact_phone)
    _create_contact_if_value(person, ContactType.WEBSITE, submission.contact_website)

    _create_external_if_url(person, ExternalLinkKind.BALLOTPEDIA, submission.link_ballotpedia)
    _create_external_if_url(person, ExternalLinkKind.WIKIPEDIA, submission.link_wikipedia)
    _create_external_if_url(person, ExternalLinkKind.OFFICIAL_SITE, submission.link_official_site)

    _create_social_if_url(person, SocialPlatform.X, submission.social_x)
    _create_social_if_url(person, SocialPlatform.FACEBOOK, submission.social_facebook)
    _create_social_if_url(person, SocialPlatform.INSTAGRAM, submission.social_instagram)
    _create_social_if_url(person, SocialPlatform.YOUTUBE, submission.social_youtube)
    _create_social_if_url(person, SocialPlatform.TIKTOK, submission.social_tiktok)
    _create_social_if_url(person, SocialPlatform.LINKEDIN, submission.social_linkedin)

    vid = extract_youtube_video_id(submission.video_interview_url or "")
    if vid:
        embed, created = VideoEmbed.objects.get_or_create(
            provider=VideoProvider.YOUTUBE,
            provider_video_id=vid,
            defaults={
                "person": person,
                "source_url": (submission.video_interview_url or "").strip(),
                "title": "",
                "is_approved": False,
                "review_status": ReviewStatus.NEEDS_REVIEW,
            },
        )
        if not created and embed.person_id is None:
            embed.person = person
            if submission.video_interview_url:
                embed.source_url = submission.video_interview_url.strip()
            embed.review_status = ReviewStatus.NEEDS_REVIEW
            embed.save(update_fields=["person", "source_url", "review_status", "updated_at"])

    submission.status = SubmissionStatus.APPROVED
    submission.reviewed_at = timezone.now()
    submission.review_notes = review_notes.strip()
    submission.created_person = person
    submission.save(
        update_fields=["status", "reviewed_at", "review_notes", "created_person", "updated_at"]
    )
    return person


@transaction.atomic
def reject_submission(submission: ProfileSubmission, review_notes: str = "") -> None:
    if submission.status != SubmissionStatus.PENDING:
        raise ValueError("Only pending submissions can be rejected.")
    submission.status = SubmissionStatus.REJECTED
    submission.reviewed_at = timezone.now()
    submission.review_notes = review_notes.strip()
    submission.save(update_fields=["status", "reviewed_at", "review_notes", "updated_at"])
