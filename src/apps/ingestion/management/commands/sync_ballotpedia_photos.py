from __future__ import annotations

import hashlib
import time
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.ingestion.http.ballotpedia import BallotpediaClient, BallotpediaError
from apps.ingestion.models import Provider, SourceRecord, SyncRun, SyncStatus
from apps.people.models import ExternalLink, ExternalLinkKind, Person


def _external_id_for_url(url: str) -> str:
    h = hashlib.sha1((url or "").encode("utf-8", "ignore")).hexdigest()
    return f"ballotpedia:photo:{h}"


def _is_placeholder_photo(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return True
    if u.endswith(".svg"):
        return True
    if "bp-logo" in u or "ballotpedia-logo" in u:
        return True
    if "submitphoto" in u:
        return True
    return False


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
            "--fresh-days",
            type=int,
            default=30,
            help="Skip refetch if we already fetched this Ballotpedia URL within N days (default: 30).",
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
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])

        run = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.RUNNING, stats={"mode": "photos"})
        client = BallotpediaClient(timeout_s=30)
        ct_person = ContentType.objects.get_for_model(Person)

        fetched = 0
        updated = 0
        skipped = 0
        errors = 0

        # People with Ballotpedia link, prefer those missing photos.
        link_qs = ExternalLink.objects.filter(kind=ExternalLinkKind.BALLOTPEDIA).exclude(url="")
        people_qs = Person.objects.filter(external_links__in=link_qs).distinct()

        if ballotpedia_url_only:
            people_qs = people_qs.filter(
                external_links__kind=ExternalLinkKind.BALLOTPEDIA,
                external_links__url=ballotpedia_url_only,
            )
        if person_id_only:
            people_qs = people_qs.filter(id=person_id_only)
        if person_public_id_only:
            people_qs = people_qs.filter(public_id=person_public_id_only)

        if state and not (ballotpedia_url_only or person_id_only or person_public_id_only):
            people_qs = people_qs.filter(
                Q(candidacies__race__office__jurisdiction__state=state)
                | Q(officeholder_terms__office__jurisdiction__state=state)
            ).distinct()

        if not force:
            # Only attempt people who appear to need a non-placeholder photo.
            people_qs = people_qs.filter(manual_photo_url="").filter(
                Q(photo_url="")
                | Q(photo_url__icontains="submitphoto")
                | Q(photo_url__icontains="bp-logo")
                | Q(photo_url__icontains="ballotpedia-logo")
                | Q(photo_url__iendswith=".svg")
            )

        # Prioritize people that were recently touched by syncs / edits.
        people_qs = people_qs.order_by("-updated_at")
        people = list(people_qs[:limit])

        for person in people:
            url = (
                person.external_links.filter(kind=ExternalLinkKind.BALLOTPEDIA)
                .exclude(url="")
                .values_list("url", flat=True)
                .first()
            )
            if not url:
                skipped += 1
                continue
            if not client.is_allowed_ballotpedia_url(url):
                skipped += 1
                continue

            external_id = _external_id_for_url(url)
            now = timezone.now()

            if not force and fresh_days:
                cutoff = now - timedelta(days=fresh_days)
                recent = (
                    SourceRecord.objects.filter(provider=Provider.BALLOTPEDIA, external_id=external_id)
                    .filter(fetched_at__gte=cutoff)
                    .order_by("-fetched_at")
                    .first()
                )
                if recent:
                    image_url = str((recent.payload or {}).get("image_url") or "").strip()
                    needs_photo = (not person.manual_photo_url) and (
                        (not person.photo_url) or _is_placeholder_photo(person.photo_url)
                    )
                    if image_url and not _is_placeholder_photo(image_url):
                        if force or needs_photo:
                            if not dry_run:
                                person.photo_url = image_url
                                person.save(update_fields=["photo_url", "updated_at"])
                            updated += 1
                        else:
                            skipped += 1
                        continue
                    # If the recent fetch didn't yield a usable image URL, try again (extractors improve).

            try:
                result = client.get_headshot(url)
                fetched += 1
                payload: dict[str, object] = {
                    "ballotpedia_url": url,
                    "image_url": result.image_url if result else "",
                    "method": result.method if result else "",
                    "html_sha256": result.html_sha256 if result else "",
                    "fetched_bytes": result.fetched_bytes if result else 0,
                }
            except BallotpediaError as exc:
                errors += 1
                payload = {"ballotpedia_url": url, "error": str(exc), "image_url": ""}
            except Exception as exc:
                errors += 1
                payload = {"ballotpedia_url": url, "error": f"Unexpected error: {exc}", "image_url": ""}

            if not dry_run:
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
                            "normalized_object_id": person.id,
                        },
                    )
                    # keep linkage consistent
                    if sr.normalized_object_id != person.id or sr.normalized_content_type_id != ct_person.id:
                        sr.normalized_content_type = ct_person
                        sr.normalized_object_id = person.id
                        sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])

                    image_url = str(payload.get("image_url") or "").strip()
                    needs_photo = (not person.manual_photo_url) and (
                        (not person.photo_url) or _is_placeholder_photo(person.photo_url)
                    )
                    if image_url and (force or needs_photo):
                        person.photo_url = image_url
                        person.save(update_fields=["photo_url", "updated_at"])
                        updated += 1

            if sleep_ms:
                time.sleep(sleep_ms / 1000.0)

            if (fetched + skipped + errors) % 25 == 0:
                run.stats = {
                    "mode": "photos",
                    "fetched": fetched,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                    "limit": limit,
                }
                run.save(update_fields=["stats", "updated_at"])

        run.stats = {
            "mode": "photos",
            "fetched": fetched,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "limit": limit,
            "dry_run": dry_run,
            "force": force,
            "fresh_days": fresh_days,
        }
        run.status = SyncStatus.SUCCESS if errors == 0 else SyncStatus.PARTIAL
        run.finished_at = timezone.now()
        run.save(update_fields=["stats", "status", "finished_at", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"ballotpedia_photos: fetched={fetched} updated={updated} skipped={skipped} errors={errors} sync_run={run.public_id.hex}"))

