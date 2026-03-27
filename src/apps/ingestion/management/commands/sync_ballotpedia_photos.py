from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from apps.ingestion.http.ballotpedia import BallotpediaClient, BallotpediaError
from apps.ingestion.models import Provider, SourceRecord, SyncRun, SyncStatus
from apps.elections.models import Candidacy, OfficeholderTerm
from apps.offices.models import OfficeLevel
from apps.people.models import (
    ContactMethod,
    ContactType,
    ExternalLink,
    ExternalLinkKind,
    Person,
    SocialLink,
    SocialPlatform,
)


def _external_id_for_url(url: str) -> str:
    h = hashlib.sha1((url or "").encode("utf-8", "ignore")).hexdigest()
    return f"ballotpedia:photo:{h}"


def _is_placeholder_photo(url: str) -> bool:
    raw = (url or "").strip()
    u = raw.lower()
    if not u:
        return True
    try:
        path = (urlparse(raw).path or "").lower()
    except Exception:
        path = ""
    if path.endswith(".svg"):
        return True
    if "bp-logo" in u or "ballotpedia-logo" in u:
        return True
    if "submitphoto" in u:
        return True
    if "flag_of_" in u:
        return True
    return False


def _tokens_from_ballotpedia_profile_url(url: str) -> list[str]:
    """
    Extract conservative tokens from a Ballotpedia profile URL.
    Example: https://ballotpedia.org/Alan_Wheeler -> ["alan", "wheeler"]
    """
    raw = (url or "").strip()
    if not raw:
        return []
    try:
        path = urlparse(raw).path or ""
        slug = unquote(path.rsplit("/", 1)[-1]).strip().lower()
    except Exception:
        slug = ""
    if not slug:
        return []
    tokens = [t for t in slug.replace("_", " ").replace("-", " ").split() if t]
    tokens = [t for t in tokens if len(t) >= 3]
    return tokens[:6]


class Command(BaseCommand):
    help = "Enrich Person.photo_url from Ballotpedia profile pages referenced by ExternalLink(kind=ballotpedia)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=250, help="Max people to process (default: 250).")
        parser.add_argument("--state", type=str, default="", help="Optional 2-letter state code to prioritize (e.g. TX).")
        parser.add_argument("--ballotpedia-url", type=str, default="", help="Process only this Ballotpedia URL.")
        parser.add_argument("--person-id", type=int, default=0, help="Process only this Person.id.")
        parser.add_argument("--person-public-id", type=str, default="", help="Process only this Person.public_id (UUID).")
        parser.add_argument("--sleep-ms", type=int, default=300, help="Delay between requests (default: 300ms).")
        parser.add_argument(
            "--s3-only",
            action="store_true",
            help="Only probe Ballotpedia's public S3 headshot URLs; do not fetch Ballotpedia HTML pages.",
        )
        parser.add_argument(
            "--record-misses",
            action="store_true",
            help="Store SourceRecord rows even when no usable image is found (slower).",
        )
        parser.add_argument(
            "--max-runtime-s",
            type=int,
            default=0,
            help="Optional wall-clock cutoff for long runs (seconds). 0 means no cutoff.",
        )
        parser.add_argument(
            "--force-run",
            action="store_true",
            help="Allow running even if another Ballotpedia sync is marked RUNNING.",
        )
        parser.add_argument(
            "--allow-overlap",
            action="store_true",
            help="Allow multiple concurrent photo sync processes (not recommended).",
        )
        parser.add_argument(
            "--progress-every-s",
            type=int,
            default=10,
            help="Print progress every N seconds (default: 10).",
        )
        parser.add_argument(
            "--print-errors",
            action="store_true",
            help="Print per-URL errors as they happen (capped).",
        )
        parser.add_argument(
            "--max-printed-errors",
            type=int,
            default=20,
            help="Max number of per-URL errors to print (default: 20).",
        )
        parser.add_argument(
            "--timeout-s",
            type=int,
            default=12,
            help="HTTP timeout for Ballotpedia requests (default: 12).",
        )
        parser.add_argument(
            "--fresh-days",
            type=int,
            default=30,
            help="Skip refetch if we already fetched this Ballotpedia URL within N days (default: 30).",
        )
        parser.add_argument(
            "--audit-existing",
            action="store_true",
            help="Re-fetch and reconcile existing Ballotpedia-derived Person.photo_url values (clears wrong ones).",
        )
        parser.add_argument(
            "--with-contact",
            action="store_true",
            help="Also extract public website/social/email/phone from Ballotpedia pages and upsert into our models (slower).",
        )
        parser.add_argument(
            "--only-missing-contact",
            action="store_true",
            help="With --with-contact, only process people missing website/social contact info (faster).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite Person.photo_url even if set, and refetch even if fresh.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Do not write DB changes.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"] or 1))
        state = (options.get("state") or "").strip().upper()
        ballotpedia_url_only = (options.get("ballotpedia_url") or "").strip()
        person_id_only = int(options.get("person_id") or 0)
        person_public_id_only = (options.get("person_public_id") or "").strip()
        sleep_ms = max(0, int(options["sleep_ms"] or 0))
        fresh_days = max(0, int(options["fresh_days"] or 0))
        audit_existing = bool(options.get("audit_existing"))
        with_contact = bool(options.get("with_contact"))
        only_missing_contact = bool(options.get("only_missing_contact"))
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])
        s3_only = bool(options.get("s3_only"))
        record_misses = bool(options.get("record_misses"))
        max_runtime_s = max(0, int(options.get("max_runtime_s") or 0))
        force_run = bool(options.get("force_run"))
        allow_overlap = bool(options.get("allow_overlap"))
        progress_every_s = max(0, int(options.get("progress_every_s") or 0))
        print_errors = bool(options.get("print_errors"))
        max_printed_errors = max(0, int(options.get("max_printed_errors") or 0))
        timeout_s = max(1, int(options.get("timeout_s") or 12))

        now = timezone.now()

        existing_running = (
            SyncRun.objects.filter(provider=Provider.BALLOTPEDIA, status=SyncStatus.RUNNING)
            .order_by("-created_at")
            .first()
        )
        if existing_running and not force_run:
            # Mark stale runs as failed so they don't block forever.
            age_s = 0
            try:
                age_s = int((now - (existing_running.started_at or existing_running.created_at)).total_seconds())
            except Exception:
                age_s = 0
            updated_age_s = 0
            try:
                updated_age_s = int((now - (existing_running.updated_at or existing_running.created_at)).total_seconds())
            except Exception:
                updated_age_s = 0
            # This command saves stats every ~5s; if we haven't updated in minutes, it's almost certainly dead/stuck.
            is_stale = age_s > 60 * 60 or updated_age_s > 5 * 60
            if is_stale:
                existing_running.status = SyncStatus.FAILED
                reason = "Marked stale by sync_ballotpedia_photos."
                if updated_age_s > 5 * 60:
                    reason = f"Marked stale by sync_ballotpedia_photos (no progress for {updated_age_s}s)."
                existing_running.error_text = (existing_running.error_text + "\n" if existing_running.error_text else "") + reason
                existing_running.finished_at = now
                existing_running.save(update_fields=["status", "error_text", "finished_at", "updated_at"])
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"Another Ballotpedia photo sync is already running (sync_run={existing_running.public_id.hex}). "
                        "Use --force-run to override."
                    )
                )
                return

        # Prevent accidental overlaps (these are network-bound and will just slow each other down).
        lock_state = state or "all"
        lock_key = f"lock:sync:ballotpedia_photos:{lock_state}"
        have_lock = True
        if not allow_overlap:
            have_lock = False
            timeout_s = max(60, max_runtime_s or (60 * 60))
            for attempt in range(2):
                if cache.add(lock_key, "1", timeout=timeout_s):
                    have_lock = True
                    break
                # If no SyncRun is actually running, the lock is stale; clear and retry once.
                if attempt == 0 and not SyncRun.objects.filter(provider=Provider.BALLOTPEDIA, status=SyncStatus.RUNNING).exists():
                    cache.delete(lock_key)
                    continue
                break
            if not have_lock:
                self.stdout.write(
                    self.style.ERROR(
                        "Another Ballotpedia photo sync is already in progress (lock held). "
                        "Wait for it to finish, or pass --allow-overlap (not recommended)."
                    )
                )
                return

        run = None
        try:
            run = SyncRun.objects.create(
                provider=Provider.BALLOTPEDIA,
                status=SyncStatus.RUNNING,
                stats={
                    "mode": "photos",
                    "audit_existing": audit_existing,
                    "s3_only": s3_only,
                    "record_misses": record_misses,
                    "max_runtime_s": max_runtime_s,
                    "state": state,
                },
            )
            # Keep timeouts reasonably short; allow override for flaky networks.
            client = BallotpediaClient(timeout_s=timeout_s)
            ct_person = ContentType.objects.get_for_model(Person)

            fetched = 0
            updated = 0
            cleared = 0
            skipped = 0
            errors = 0

            # People with Ballotpedia link (avoid N+1 queries by annotating the URL).
            bp_url_sq = (
                ExternalLink.objects.filter(person_id=OuterRef("pk"), kind=ExternalLinkKind.BALLOTPEDIA)
                .exclude(url="")
                .values("url")[:1]
            )
            people_qs = Person.objects.annotate(bp_url=Subquery(bp_url_sq)).exclude(bp_url__isnull=True).exclude(bp_url="")

            if ballotpedia_url_only:
                people_qs = people_qs.filter(bp_url=ballotpedia_url_only)
            if person_id_only:
                people_qs = people_qs.filter(id=person_id_only)
            if person_public_id_only:
                people_qs = people_qs.filter(public_id=person_public_id_only)

            if state and not (ballotpedia_url_only or person_id_only or person_public_id_only):
                # Avoid expensive JOIN+DISTINCT across large tables by using EXISTS subqueries.
                tx_cand = Candidacy.objects.filter(person_id=OuterRef("pk")).filter(race__office__jurisdiction__state=state)
                tx_term = OfficeholderTerm.objects.filter(person_id=OuterRef("pk")).filter(office__jurisdiction__state=state)
                people_qs = people_qs.annotate(_tx=Exists(tx_cand) | Exists(tx_term)).filter(_tx=True)

                # Prioritize higher-level offices first (more likely to have headshots).
                hi_cand = (
                    Candidacy.objects.filter(person_id=OuterRef("pk"))
                    .filter(race__office__jurisdiction__state=state)
                    .filter(race__office__level__in=[OfficeLevel.FEDERAL, OfficeLevel.STATE])
                )
                hi_term = (
                    OfficeholderTerm.objects.filter(person_id=OuterRef("pk"))
                    .filter(office__jurisdiction__state=state)
                    .filter(office__level__in=[OfficeLevel.FEDERAL, OfficeLevel.STATE])
                )
                people_qs = people_qs.annotate(_hi=Exists(hi_cand) | Exists(hi_term))

            if with_contact and only_missing_contact and not (ballotpedia_url_only or person_id_only or person_public_id_only):
                has_site = ContactMethod.objects.filter(person_id=OuterRef("pk"), contact_type=ContactType.WEBSITE).exclude(
                    value=""
                )
                has_social = SocialLink.objects.filter(person_id=OuterRef("pk")).exclude(url="")
                people_qs = people_qs.annotate(_has_site=Exists(has_site), _has_social=Exists(has_social)).filter(
                    Q(_has_site=False) | Q(_has_social=False)
                )

            if not (force or audit_existing):
                # Only attempt people who appear to need a non-placeholder photo.
                people_qs = people_qs.filter(manual_photo_url="").filter(
                    Q(photo_url="")
                    | Q(photo_url__icontains="submitphoto")
                    | Q(photo_url__icontains="bp-logo")
                    | Q(photo_url__icontains="ballotpedia-logo")
                    | Q(photo_url__icontains="flag_of_")
                    | Q(photo_url__iendswith=".svg")
                )
            elif audit_existing and not force:
                # Audit mode: focus on existing provider-derived photos.
                people_qs = people_qs.filter(manual_photo_url="")
                # If the user targets a specific person/URL, still allow processing even if photo_url is blank.
                if not (ballotpedia_url_only or person_id_only or person_public_id_only):
                    people_qs = people_qs.filter(
                        Q(photo_url__icontains="ballotpedia-api4/files") | Q(photo_url__icontains="ballotpedia.org")
                    )

            # Order: higher-level offices first (when available), then most recently updated.
            order_fields = ["-updated_at"]
            if state and not (ballotpedia_url_only or person_id_only or person_public_id_only):
                order_fields = ["-_hi", *order_fields]
            people_qs = people_qs.order_by(*order_fields).values("id", "bp_url", "photo_url", "manual_photo_url")[:limit]
            people = list(people_qs)

            self.stdout.write(
                f"Ballotpedia photo sync starting: state={state or '-'} s3_only={s3_only} limit={limit} targets={len(people)}"
            )

            def _photo_is_ballotpedia_derived(url: str) -> bool:
                raw = (url or "").strip()
                if not raw:
                    return False
                try:
                    host = (urlparse(raw).hostname or "").lower()
                except Exception:
                    host = ""
                low = raw.lower()
                return ("ballotpedia-api4/files" in low) or (host == "ballotpedia.org") or host.endswith(".ballotpedia.org")

            def upsert_contacts(person_id: int, contacts_payload: object) -> None:
                if not with_contact:
                    return
                if not isinstance(contacts_payload, dict):
                    return
                try:
                    emails = list(contacts_payload.get("emails") or []) if isinstance(contacts_payload.get("emails"), list) else []
                    phones = list(contacts_payload.get("phones") or []) if isinstance(contacts_payload.get("phones"), list) else []
                    websites = (
                        list(contacts_payload.get("websites") or []) if isinstance(contacts_payload.get("websites"), list) else []
                    )
                    socials = (
                        list(contacts_payload.get("socials") or []) if isinstance(contacts_payload.get("socials"), list) else []
                    )
                except Exception:
                    emails, phones, websites, socials = [], [], [], []

                if emails:
                    ContactMethod.objects.update_or_create(
                        person_id=person_id,
                        contact_type=ContactType.EMAIL,
                        label="Ballotpedia email",
                        defaults={"value": str(emails[0]).strip(), "is_public": True},
                    )
                if phones:
                    ContactMethod.objects.update_or_create(
                        person_id=person_id,
                        contact_type=ContactType.PHONE,
                        label="Ballotpedia phone",
                        defaults={"value": str(phones[0]).strip(), "is_public": True},
                    )
                if websites:
                    site = str(websites[0]).strip()
                    if site:
                        ContactMethod.objects.update_or_create(
                            person_id=person_id,
                            contact_type=ContactType.WEBSITE,
                            label="Ballotpedia website",
                            defaults={"value": site, "is_public": True},
                        )
                        ExternalLink.objects.get_or_create(
                            person_id=person_id,
                            kind=ExternalLinkKind.OFFICIAL_SITE,
                            url=site,
                            defaults={"label": "Official website"},
                        )
                for s in socials[:6]:
                    low = str(s or "").lower()
                    platform = ""
                    if "x.com/" in low or "twitter.com/" in low:
                        platform = SocialPlatform.X
                    elif "facebook.com/" in low:
                        platform = SocialPlatform.FACEBOOK
                    elif "instagram.com/" in low:
                        platform = SocialPlatform.INSTAGRAM
                    elif "youtube.com/" in low:
                        platform = SocialPlatform.YOUTUBE
                    elif "tiktok.com/" in low:
                        platform = SocialPlatform.TIKTOK
                    elif "linkedin.com/" in low:
                        platform = SocialPlatform.LINKEDIN
                    if not platform:
                        continue
                    SocialLink.objects.get_or_create(
                        person_id=person_id,
                        platform=platform,
                        url=str(s).strip(),
                        defaults={"handle": ""},
                    )

            started_monotonic = time.monotonic()
            last_stats_save = started_monotonic
            last_progress_print = started_monotonic
            printed_errors = 0

            def maybe_save_stats(force_save: bool = False):
                nonlocal last_stats_save
                if not force_save and (time.monotonic() - last_stats_save) < 5.0:
                    return
                if run:
                    run.stats = {
                        "mode": "photos",
                        "fetched": fetched,
                        "updated": updated,
                        "cleared": cleared,
                        "skipped": skipped,
                        "errors": errors,
                        "limit": limit,
                        "dry_run": dry_run,
                        "force": force,
                        "fresh_days": fresh_days,
                        "audit_existing": audit_existing,
                        "s3_only": s3_only,
                        "record_misses": record_misses,
                        "max_runtime_s": max_runtime_s,
                        "state": state,
                        "elapsed_s": int(time.monotonic() - started_monotonic),
                    }
                    run.save(update_fields=["stats", "updated_at"])
                last_stats_save = time.monotonic()

            def maybe_print_progress(idx: int, total: int, url: str):
                nonlocal last_progress_print
                if not progress_every_s:
                    return
                if (time.monotonic() - last_progress_print) < float(progress_every_s):
                    return
                elapsed = max(1.0, time.monotonic() - started_monotonic)
                rate = (idx / elapsed) if idx else 0.0
                self.stdout.write(
                    f"[{idx}/{total}] fetched={fetched} updated={updated} cleared={cleared} skipped={skipped} errors={errors} "
                    f"rate={rate:.2f}/s url={url}"
                )
                last_progress_print = time.monotonic()

            cutoff_reached = False
            for idx, row in enumerate(people, start=1):
                if max_runtime_s and (time.monotonic() - started_monotonic) > max_runtime_s:
                    cutoff_reached = True
                    break

                url = str(row.get("bp_url") or "").strip()
                if not url:
                    skipped += 1
                    continue
                if not client.is_allowed_ballotpedia_url(url):
                    skipped += 1
                    continue

                # In audit mode, focus on suspicious existing photos: those that don't even
                # appear to match the Ballotpedia slug (fast, avoids re-fetching thousands).
                if audit_existing and not force:
                    tokens = _tokens_from_ballotpedia_profile_url(url)
                    current_photo = str(row.get("photo_url") or "")
                    token_hits = sum(1 for t in tokens if t in current_photo.lower())
                    if current_photo and _photo_is_ballotpedia_derived(current_photo) and token_hits > 0:
                        skipped += 1
                        continue

                external_id = _external_id_for_url(url)
                now = timezone.now()

                force_fetch = force or audit_existing
                if not force_fetch and fresh_days:
                    cutoff = now - timedelta(days=fresh_days)
                    recent = (
                        SourceRecord.objects.filter(provider=Provider.BALLOTPEDIA, external_id=external_id)
                        .filter(fetched_at__gte=cutoff)
                        .order_by("-fetched_at")
                        .first()
                    )
                    if recent:
                        image_url = str((recent.payload or {}).get("image_url") or "").strip()
                        recent_contacts = (recent.payload or {}).get("contacts") if isinstance(recent.payload, dict) else None
                        manual_photo_url = str(row.get("manual_photo_url") or "").strip()
                        current_photo = str(row.get("photo_url") or "").strip()
                        needs_photo = (not manual_photo_url) and (not current_photo or _is_placeholder_photo(current_photo))
                        if with_contact and recent_contacts and not dry_run:
                            upsert_contacts(int(row["id"]), recent_contacts)
                        if image_url and not _is_placeholder_photo(image_url):
                            if force or needs_photo or audit_existing:
                                if not dry_run:
                                    Person.objects.filter(id=int(row["id"])).update(photo_url=image_url, updated_at=now)
                                updated += 1
                            else:
                                skipped += 1
                            continue
                        # If we already got contacts recently and we don't need a photo, avoid re-fetching.
                        if with_contact and recent_contacts and not needs_photo:
                            skipped += 1
                            continue
                        # If the recent fetch didn't yield a usable image URL, try again (extractors improve).

                try:
                    if s3_only:
                        # "No HTML" mode: only probe Ballotpedia's public S3 headshot URLs.
                        result = client.guess_headshot(url)
                    else:
                        # Fast guess first (works even when HTML is blocked).
                        result = client.guess_headshot(url)
                    html = ""
                    contacts: dict[str, object] = {}

                    # If we need contact data, or if guessing failed, try to fetch HTML and extract more.
                    if (with_contact and not s3_only) or (not result and not s3_only):
                        try:
                            html = client.fetch_html(url)
                            if not result:
                                result = client.extract_headshot(ballotpedia_url=url, html=html)
                        except BallotpediaError:
                            html = ""

                    fetched += 1
                    payload = {
                        "ballotpedia_url": url,
                        "image_url": result.image_url if result else "",
                        "method": result.method if result else "",
                        "html_sha256": result.html_sha256 if result else "",
                        "fetched_bytes": result.fetched_bytes if result else 0,
                    }
                    if with_contact and html:
                        # Conservative extraction: only infobox <a href> links.
                        class _InfoboxHrefParser(HTMLParser):
                            def __init__(self) -> None:
                                super().__init__(convert_charrefs=True)
                                self._in_infobox_person = False
                                self._infobox_depth = 0
                                self.hrefs: list[str] = []

                            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                                a = {k.lower(): (v or "") for k, v in attrs}
                                if tag.lower() in {"table", "div"}:
                                    cls = (a.get("class") or "").lower()
                                    if "infobox-person" in cls or ("infobox" in cls and "person" in cls):
                                        self._in_infobox_person = True
                                        self._infobox_depth = 1
                                    elif self._in_infobox_person and tag.lower() in {"table", "div"}:
                                        self._infobox_depth += 1
                                if tag.lower() == "a" and self._in_infobox_person and len(self.hrefs) < 80:
                                    href = (a.get("href") or "").strip()
                                    if href:
                                        self.hrefs.append(href)

                            def handle_endtag(self, tag: str) -> None:
                                if tag.lower() in {"table", "div"} and self._in_infobox_person:
                                    self._infobox_depth = max(0, self._infobox_depth - 1)
                                    if self._infobox_depth == 0:
                                        self._in_infobox_person = False

                        p = _InfoboxHrefParser()
                        p.feed(html)
                        p.close()

                        emails: list[str] = []
                        phones: list[str] = []
                        websites: list[str] = []
                        socials: list[str] = []
                        for href in p.hrefs:
                            h = (href or "").strip()
                            if h.startswith("mailto:"):
                                emails.append(h.split("mailto:", 1)[-1].split("?", 1)[0].strip())
                                continue
                            if h.startswith("tel:"):
                                phones.append(h.split("tel:", 1)[-1].strip())
                                continue
                            if not h.startswith(("http://", "https://")):
                                continue
                            low = h.lower()
                            # Skip internal Ballotpedia links and common asset hosts.
                            if "ballotpedia.org" in low:
                                continue
                            if "s3.amazonaws.com" in low or "ballotpedia.s3.amazonaws.com" in low:
                                continue
                            if any(
                                host in low
                                for host in (
                                    "facebook.com",
                                    "x.com",
                                    "twitter.com",
                                    "instagram.com",
                                    "youtube.com",
                                    "tiktok.com",
                                    "linkedin.com",
                                )
                            ):
                                socials.append(h)
                            else:
                                websites.append(h)

                        # Deduplicate while preserving order.
                        def _dedupe(xs: list[str]) -> list[str]:
                            seen = set()
                            out = []
                            for x in xs:
                                xx = (x or "").strip()
                                if not xx or xx in seen:
                                    continue
                                seen.add(xx)
                                out.append(xx)
                            return out
                        contacts = {
                            "emails": _dedupe(emails)[:3],
                            "phones": _dedupe(phones)[:3],
                            "websites": _dedupe(websites)[:5],
                            "socials": _dedupe(socials)[:10],
                        }
                        payload["contacts"] = contacts
                except BallotpediaError as exc:
                    errors += 1
                    payload = {"ballotpedia_url": url, "error": str(exc), "image_url": ""}
                    if print_errors and printed_errors < max_printed_errors:
                        self.stdout.write(self.style.WARNING(f"ERR ballotpedia_url={url} error={exc}"))
                        printed_errors += 1
                except Exception as exc:
                    errors += 1
                    payload = {"ballotpedia_url": url, "error": f"Unexpected error: {exc}", "image_url": ""}
                    if print_errors and printed_errors < max_printed_errors:
                        self.stdout.write(self.style.WARNING(f"ERR ballotpedia_url={url} error={exc}"))
                        printed_errors += 1

                image_url = str(payload.get("image_url") or "").strip()
                has_contacts = bool(payload.get("contacts")) if isinstance(payload, dict) else False
                should_write = (not dry_run) and (record_misses or bool(image_url) or has_contacts or "error" in payload)
                if should_write:
                    with transaction.atomic():
                        sha = SourceRecord.compute_sha256(payload)
                        sr, _ = SourceRecord.objects.get_or_create(
                            provider=Provider.BALLOTPEDIA,
                            external_id=external_id,
                            payload_sha256=sha,
                            defaults={
                                "payload": payload,
                                "fetched_at": now,
                                "source_url": url,
                                "source_name": "Ballotpedia",
                                "sync_run": run,
                                "normalized_content_type": ct_person,
                                "normalized_object_id": int(row["id"]),
                            },
                        )
                        # keep linkage consistent
                        if sr.normalized_object_id != int(row["id"]) or sr.normalized_content_type_id != ct_person.id:
                            sr.normalized_content_type = ct_person
                            sr.normalized_object_id = int(row["id"])
                            sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])

                        manual_photo_url = str(row.get("manual_photo_url") or "").strip()
                        current_photo = str(row.get("photo_url") or "").strip()
                        needs_photo = (not manual_photo_url) and (not current_photo or _is_placeholder_photo(current_photo))
                        if image_url and not _is_placeholder_photo(image_url) and (force or needs_photo or audit_existing):
                            current = str(row.get("photo_url") or "")
                            if current != image_url:
                                Person.objects.filter(id=int(row["id"])).update(photo_url=image_url, updated_at=now)
                                updated += 1
                        # Best-effort: upsert contact info extracted from Ballotpedia HTML.
                        if with_contact and not dry_run:
                            upsert_contacts(int(row["id"]), payload.get("contacts"))
                        elif (force or audit_existing) and (not manual_photo_url) and _photo_is_ballotpedia_derived(current_photo):
                            # If we can't confidently extract a headshot now, it's safer to clear an existing
                            # Ballotpedia-derived photo than to keep a potentially wrong one.
                            tokens = _tokens_from_ballotpedia_profile_url(url)
                            token_hits = sum(1 for t in tokens if t in current_photo.lower())
                            # Only clear when the current image doesn't even appear to match the profile slug.
                            if current_photo and token_hits == 0:
                                Person.objects.filter(id=int(row["id"])).update(photo_url="", updated_at=now)
                                cleared += 1

                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

                maybe_save_stats()
                maybe_print_progress(idx, len(people), url)

            maybe_save_stats(force_save=True)
            if run:
                run.stats = {**(run.stats or {}), "cutoff_reached": cutoff_reached}
                run.status = SyncStatus.SUCCESS if errors == 0 else SyncStatus.PARTIAL
                run.finished_at = timezone.now()
                run.save(update_fields=["stats", "status", "finished_at", "updated_at"])

                self.stdout.write(
                    self.style.SUCCESS(
                        f"ballotpedia_photos: fetched={fetched} updated={updated} cleared={cleared} skipped={skipped} errors={errors} sync_run={run.public_id.hex}"
                    )
                )
                if cutoff_reached and max_runtime_s:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Stopped due to --max-runtime-s={max_runtime_s}. Re-run to continue the remaining people."
                        )
                    )
        finally:
            if have_lock and not allow_overlap:
                cache.delete(lock_key)

