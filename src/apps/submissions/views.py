from __future__ import annotations

import logging
import secrets
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import ProfileSubmissionForm, ReviewNotesForm, StaffLoginForm
from .mail import notify_new_submission
from .models import ProfileSubmission, SubmissionStatus
from .services import approve_submission, reject_submission

logger = logging.getLogger(__name__)

STAFF_SESSION_KEY = "submissions_staff_ok"


def _staff_pin_ok(code: str) -> bool:
    expected = getattr(settings, "SUBMISSIONS_STAFF_PIN", "") or ""
    if not expected:
        return False
    try:
        return secrets.compare_digest(code.strip(), expected)
    except Exception:
        return False


def staff_required(view):
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not request.session.get(STAFF_SESSION_KEY):
            return redirect("submissions:staff_login")
        return view(request, *args, **kwargs)

    return wrapped


@require_http_methods(["GET", "POST"])
def profile_submit(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProfileSubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save()
            try:
                notify_new_submission(
                    submission,
                    staff_detail_absolute_url=request.build_absolute_uri(
                        reverse("submissions:staff_detail", kwargs={"pk": submission.pk})
                    ),
                )
            except Exception:
                logger.exception("Failed to send submission notification email")
            messages.success(
                request,
                "Thank you. Your profile information was submitted for review. Our team will verify it before it appears in the directory.",
            )
            return redirect("submissions:profile_submit_done")
    else:
        form = ProfileSubmissionForm()
    return render(
        request,
        "submissions/profile_submit.html",
        {"form": form},
    )


def profile_submit_done(request: HttpRequest) -> HttpResponse:
    return render(request, "submissions/profile_submit_done.html")


@require_http_methods(["GET", "POST"])
def staff_login(request: HttpRequest) -> HttpResponse:
    if request.session.get(STAFF_SESSION_KEY):
        return redirect("submissions:staff_list")
    if request.method == "POST":
        form = StaffLoginForm(request.POST)
        if form.is_valid():
            if _staff_pin_ok(form.cleaned_data["access_code"]):
                request.session.cycle_key()
                request.session[STAFF_SESSION_KEY] = True
                request.session.modified = True
                messages.success(request, "Signed in to the submissions console.")
                return redirect("submissions:staff_list")
            messages.error(request, "Invalid access code.")
    else:
        form = StaffLoginForm()
    return render(request, "submissions/staff/login.html", {"form": form})


@require_http_methods(["POST"])
def staff_logout(request: HttpRequest) -> HttpResponse:
    request.session.pop(STAFF_SESSION_KEY, None)
    messages.info(request, "Signed out.")
    return redirect("submissions:staff_login")


@staff_required
def staff_list(request: HttpRequest) -> HttpResponse:
    qs = ProfileSubmission.objects.all()
    status = (request.GET.get("status") or "").strip()
    if status in {SubmissionStatus.PENDING, SubmissionStatus.APPROVED, SubmissionStatus.REJECTED}:
        qs = qs.filter(status=status)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(submitter_email__icontains=q)
            | Q(submitter_name__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(manual_display_name__icontains=q)
        )
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page") or 1)
    return render(
        request,
        "submissions/staff/list.html",
        {
            "page_obj": page,
            "status_filter": status,
            "q": q,
            "counts": {
                "all": ProfileSubmission.objects.count(),
                "pending": ProfileSubmission.objects.filter(status=SubmissionStatus.PENDING).count(),
                "approved": ProfileSubmission.objects.filter(status=SubmissionStatus.APPROVED).count(),
                "rejected": ProfileSubmission.objects.filter(status=SubmissionStatus.REJECTED).count(),
            },
        },
    )


@staff_required
@require_http_methods(["GET", "POST"])
def staff_detail(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(ProfileSubmission.objects.all(), pk=pk)
    notes_form = ReviewNotesForm()
    if request.method == "POST":
        action = request.POST.get("action")
        notes_form = ReviewNotesForm(request.POST)
        if not notes_form.is_valid():
            messages.error(request, "Could not save notes.")
        elif action == "approve" and submission.status == SubmissionStatus.PENDING:
            try:
                person = approve_submission(submission, review_notes=notes_form.cleaned_data.get("review_notes") or "")
                messages.success(
                    request,
                    "Approved. Draft person record created (needs review in the main admin).",
                )
                return redirect("submissions:staff_detail", pk=submission.pk)
            except ValueError as e:
                messages.error(request, str(e))
        elif action == "reject" and submission.status == SubmissionStatus.PENDING:
            try:
                reject_submission(submission, review_notes=notes_form.cleaned_data.get("review_notes") or "")
                messages.warning(request, "Submission rejected.")
                return redirect("submissions:staff_detail", pk=submission.pk)
            except ValueError as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Nothing to do for this submission in its current state.")
    return render(
        request,
        "submissions/staff/detail.html",
        {
            "submission": submission,
            "notes_form": notes_form,
        },
    )
