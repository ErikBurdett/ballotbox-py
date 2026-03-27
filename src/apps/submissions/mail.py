from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .models import ProfileSubmission


def notify_new_submission(submission: ProfileSubmission, *, staff_detail_absolute_url: str | None = None) -> None:
    to = getattr(settings, "SUBMISSIONS_NOTIFY_EMAIL", None)
    if not to:
        return
    subject = f"[{getattr(settings, 'SUBMISSIONS_EMAIL_SUBJECT_PREFIX', 'Ballot Box')}] New profile submission: {submission.display_submitted_name()}"
    detail_path = reverse("submissions:staff_detail", kwargs={"pk": submission.pk})
    link_line = (
        f"\nReview (after signing in): {staff_detail_absolute_url}\n"
        if staff_detail_absolute_url
        else f"\nStaff path: {detail_path} (sign in at {reverse('submissions:staff_login')})\n"
    )
    body = (
        f"A new {submission.get_profile_role_display().lower()} profile was submitted.\n\n"
        f"Submission ID: {submission.pk}\n"
        f"Name (display): {submission.display_submitted_name()}\n"
        f"Submitter: {submission.submitter_name or '—'} <{submission.submitter_email}>\n"
        f"Office: {submission.office_name or '—'}\n"
        f"Jurisdiction: {submission.jurisdiction_name or '—'}\n"
        f"District: {submission.district_name or '—'}\n"
        f"{link_line}\n"
        f"Review in the staff console with your access code.\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
