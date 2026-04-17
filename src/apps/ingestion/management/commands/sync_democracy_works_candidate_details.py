from __future__ import annotations

import signal
import time
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.elections.models import Candidacy, OfficeholderTerm
from apps.ingestion.http.democracy_works import DemocracyWorksClient, DemocracyWorksError
from apps.ingestion.models import Provider, SourceRecord, SyncRun, SyncStatus
from apps.people.models import (
    ContactMethod,
    ContactType,
    ExternalLink,
    ExternalLinkKind,
    Party,
    Person,
    SocialLink,
    SocialPlatform,
)


def _party_from_affiliations(values: list[str] | None) -> tuple[str, str]:
    v = (values or [])
    if not v:
        return Party.UNKNOWN, ""
    first = (v[0] or "").strip()
    key = first.lower()
    mapping = {
        "democratic": Party.DEMOCRATIC,
        "democrat": Party.DEMOCRATIC,
        "republican": Party.REPUBLICAN,
        "independent": Party.INDEPENDENT,
        "libertarian": Party.LIBERTARIAN,
        "green": Party.GREEN,
        "nonpartisan": Party.NONPARTISAN,
        "non-partisan": Party.NONPARTISAN,
        "unaﬃliated": Party.INDEPENDENT,
        "unaffiliated": Party.INDEPENDENT,
    }
    party = mapping.get(key, Party.OTHER if first else Party.UNKNOWN)
    return party, first if party == Party.OTHER else ""


def _maybe_social_url(platform: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith("http://") or v.startswith("https://"):
        return v
    if platform in {SocialPlatform.X, SocialPlatform.TWITTER}:
        handle = v.lstrip("@")
        return f"https://x.com/{handle}"
    if platform == SocialPlatform.INSTAGRAM:
        handle = v.lstrip("@")
        return f"https://www.instagram.com/{handle}/"
    if platform == SocialPlatform.FACEBOOK:
        handle = v.strip("/")
        return f"https://www.facebook.com/{handle}"
    return ""


def _record_dw_source(*, sync_run: SyncRun, external_id: str, payload: dict[str, Any], normalized_obj: Any | None) -> None:
    fetched_at = timezone.now()
    sha = SourceRecord.compute_sha256(payload)
    sr, _ = SourceRecord.objects.get_or_create(
        provider=Provider.DEMOCRACY_WORKS,
        external_id=external_id,
        payload_sha256=sha,
        defaults={
            "payload": payload,
            "fetched_at": fetched_at,
            "source_url": str(payload.get("canonicalUrl") or payload.get("canonical_url") or "").strip(),
            "source_name": "Democracy Works",
            "sync_run": sync_run,
        },
    )
    if normalized_obj is not None:
        ct = ContentType.objects.get_for_model(normalized_obj.__class__)
        if sr.normalized_content_type_id != ct.id or sr.normalized_object_id != normalized_obj.id:
            sr.normalized_content_type = ct
            sr.normalized_object_id = normalized_obj.id
            sr.save(update_fields=["normalized_content_type", "normalized_object_id", "updated_at"])


def _apply_candidate_contact(person: Person, candidate_payload: dict[str, Any]) -> None:
    contact = candidate_payload.get("contact") or {}
    if not isinstance(contact, dict):
        return
    campaign = (contact.get("campaign") or {}) if isinstance(contact.get("campaign"), dict) else {}
    personal = (contact.get("personal") or {}) if isinstance(contact.get("personal"), dict) else {}

    email = str(campaign.get("email") or "").strip()
    phone = str(campaign.get("phone") or "").strip()
    website = str(campaign.get("website") or "").strip()
    mailing_address = str(campaign.get("mailingAddress") or "").strip()
    if email:
        ContactMethod.objects.update_or_create(
            person=person,
            contact_type=ContactType.EMAIL,
            label="Campaign email",
            defaults={"value": email, "is_public": True},
        )
    if phone:
        ContactMethod.objects.update_or_create(
            person=person,
            contact_type=ContactType.PHONE,
            label="Campaign phone",
            defaults={"value": phone, "is_public": True},
        )
    if website:
        ContactMethod.objects.update_or_create(
            person=person,
            contact_type=ContactType.WEBSITE,
            label="Campaign website",
            defaults={"value": website, "is_public": True},
        )
    if mailing_address:
        ContactMethod.objects.update_or_create(
            person=person,
            contact_type=ContactType.ADDRESS,
            label="Campaign mailing address",
            defaults={"value": mailing_address, "is_public": True},
        )

    personal_website = str(personal.get("website") or "").strip()
    if personal_website:
        ContactMethod.objects.update_or_create(
            person=person,
            contact_type=ContactType.WEBSITE,
            label="Personal website",
            defaults={"value": personal_website, "is_public": True},
        )

    socials = {
        SocialPlatform.FACEBOOK: [campaign.get("facebook"), personal.get("facebook")],
        SocialPlatform.TWITTER: [campaign.get("twitter"), personal.get("twitter")],
        SocialPlatform.INSTAGRAM: [campaign.get("instagram"), personal.get("instagram")],
        SocialPlatform.YOUTUBE: [campaign.get("youtube"), personal.get("youtube")],
        SocialPlatform.LINKEDIN: [campaign.get("linkedIn"), personal.get("linkedIn")],
    }
    for platform, raws in socials.items():
        for raw in raws:
            url = _maybe_social_url(platform, str(raw or ""))
            if url:
                SocialLink.objects.get_or_create(person=person, platform=platform, url=url)
                break


class Command(BaseCommand):
    help = "Fetch Democracy Works candidate detail + endorsements for people already ingested from elections."

    def add_arguments(self, parser):
        parser.add_argument("--state", type=str, default="", help="Optional 2-letter state code (e.g. TX).")
        parser.add_argument("--limit", type=int, default=500, help="Max candidates to process (default: 500).")
        parser.add_argument("--sleep-ms", type=int, default=50, help="Delay between DW requests (default: 50ms).")
        parser.add_argument("--fresh-days", type=int, default=14, help="Skip if fetched within N days (default: 14).")
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only fetch candidate_detail for candidates that do not already have one.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=25,
            help="Print progress every N candidates processed (default: 25).",
        )
        parser.add_argument(
            "--print-errors",
            action="store_true",
            help="Print per-candidate errors as they occur.",
        )
        parser.add_argument("--with-endorsements", action="store_true", help="Fetch endorsement details (default: off).")
        parser.add_argument(
            "--endorsements-only",
            action="store_true",
            help="Only fetch endorsements (skip candidate detail fetch/normalization).",
        )
        parser.add_argument(
            "--only-missing-endorsements",
            action="store_true",
            help="When fetching endorsements, only process people that do not already have any candidate_endorsements records.",
        )
        parser.add_argument("--endorsements-page-size", type=int, default=50, help="Endorsements page size (default: 50).")
        parser.add_argument("--endorsements-max-pages", type=int, default=10, help="Max endorsements pages (default: 10).")

    def handle(self, *args, **options):
        state = (options.get("state") or "").strip().upper()
        limit = max(1, int(options.get("limit") or 1))
        sleep_ms = max(0, int(options.get("sleep_ms") or 0))
        fresh_days = max(0, int(options.get("fresh_days") or 0))
        only_missing = bool(options.get("only_missing"))
        progress_every = max(1, int(options.get("progress_every") or 25))
        print_errors = bool(options.get("print_errors"))
        with_endorsements = bool(options.get("with_endorsements"))
        endorsements_only = bool(options.get("endorsements_only"))
        only_missing_endorsements = bool(options.get("only_missing_endorsements"))
        endorsements_page_size = min(max(1, int(options.get("endorsements_page_size") or 50)), 100)
        endorsements_max_pages = max(0, int(options.get("endorsements_max_pages") or 0))

        lock_key = f"lock:dw:candidate_details:{state or 'ALL'}"
        if not cache.add(lock_key, "1", timeout=60 * 60 * 6):
            # Another run is already in-flight; exit cleanly.
            run = SyncRun.objects.create(
                provider=Provider.DEMOCRACY_WORKS,
                status=SyncStatus.CANCELLED,
                stats={
                    "mode": "candidate_details",
                    "state": state,
                    "limit": limit,
                    "fresh_days": fresh_days,
                    "with_endorsements": with_endorsements,
                    "only_missing": only_missing,
                    "endorsements_only": endorsements_only,
                    "only_missing_endorsements": only_missing_endorsements,
                },
                error_text="Another DW candidate_details sync is already running.",
                finished_at=timezone.now(),
            )
            self.stdout.write(self.style.WARNING(f"dw_candidate_details: already running (sync_run={run.public_id.hex})"))
            return

        run = SyncRun.objects.create(
            provider=Provider.DEMOCRACY_WORKS,
            status=SyncStatus.RUNNING,
            stats={
                "mode": "candidate_details",
                "state": state,
                "limit": limit,
                "fresh_days": fresh_days,
                "with_endorsements": with_endorsements,
                "only_missing": only_missing,
                "endorsements_only": endorsements_only,
                "only_missing_endorsements": only_missing_endorsements,
            },
        )

        api_key = (getattr(settings, "DEMOCRACY_WORKS_API_KEY", "") or "").strip()
        if not api_key:
            run.status = SyncStatus.CANCELLED
            run.error_text = "DEMOCRACY_WORKS_API_KEY not set; skipping DW candidate details."
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_text", "finished_at", "updated_at"])
            cache.delete(lock_key)
            self.stdout.write(self.style.WARNING(run.error_text))
            return

        def _cancel(signum, _frame):
            run.status = SyncStatus.CANCELLED
            run.error_text = f"Interrupted by signal={signum}"
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_text", "finished_at", "updated_at"])
            # ensure lock is released even on SIGTERM
            cache.delete(lock_key)
            raise SystemExit(1)

        old_int = signal.signal(signal.SIGINT, _cancel)
        old_term = signal.signal(signal.SIGTERM, _cancel)

        try:
            base_url = getattr(settings, "DEMOCRACY_WORKS_API_BASE_URL", "https://api.democracy.works/v2")
            client = DemocracyWorksClient(api_key=api_key, base_url=base_url, timeout_s=30)

            ct_person = ContentType.objects.get_for_model(Person)
            candidate_srs = SourceRecord.objects.filter(
                provider=Provider.DEMOCRACY_WORKS,
                external_id__startswith="candidate:",
                normalized_content_type=ct_person,
            )

            if state:
                tx_cand = Candidacy.objects.filter(person_id=OuterRef("normalized_object_id")).filter(
                    race__office__jurisdiction__state=state
                )
                tx_term = OfficeholderTerm.objects.filter(person_id=OuterRef("normalized_object_id")).filter(
                    office__jurisdiction__state=state
                )
                candidate_srs = candidate_srs.annotate(_tx=Exists(tx_cand) | Exists(tx_term)).filter(_tx=True)

            if only_missing and not endorsements_only:
                has_detail = SourceRecord.objects.filter(
                    provider=Provider.DEMOCRACY_WORKS,
                    external_id__startswith="candidate_detail:",
                    normalized_object_id=OuterRef("normalized_object_id"),
                )
                candidate_srs = candidate_srs.annotate(_has_detail=Exists(has_detail)).filter(_has_detail=False)

            if (with_endorsements or endorsements_only) and only_missing_endorsements:
                has_endorse = SourceRecord.objects.filter(
                    provider=Provider.DEMOCRACY_WORKS,
                    external_id__startswith="candidate_endorsements:",
                    normalized_object_id=OuterRef("normalized_object_id"),
                )
                candidate_srs = candidate_srs.annotate(_has_endorse=Exists(has_endorse)).filter(_has_endorse=False)

            # Avoid DISTINCT ON; it can be very slow on large SourceRecord tables without perfect indexes.
            # Instead, stream newest-first and de-dupe in Python until we hit `limit`.
            candidate_srs = candidate_srs.order_by("-fetched_at").only("external_id", "normalized_object_id")

            fetched = 0
            skipped = 0
            errors = 0
            endorsements_fetched = 0
            already_had_detail = 0

            cutoff = timezone.now() - timedelta(days=fresh_days) if fresh_days else None
            candidate_srs_list: list[SourceRecord] = []
            seen_candidate_ids: set[str] = set()
            self.stdout.write(f"Selecting up to {limit} candidates for details sync…")
            for sr in candidate_srs.iterator(chunk_size=2000):
                candidate_id = str(sr.external_id.split("candidate:", 1)[-1] or "").strip()
                if not candidate_id or candidate_id in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(candidate_id)
                candidate_srs_list.append(sr)
                if len(candidate_srs_list) >= limit:
                    break
            total = len(candidate_srs_list)
            self.stdout.write(f"Selected {total} candidates. Fetching candidate details…")

            for idx, sr in enumerate(candidate_srs_list, start=1):
                candidate_id = str(sr.external_id.split("candidate:", 1)[-1] or "").strip()
                if not candidate_id:
                    skipped += 1
                    continue
                person = Person.objects.filter(id=sr.normalized_object_id).first() if sr.normalized_object_id else None
                if not person:
                    skipped += 1
                    continue

                # Skip if it's fresh enough.
                existing_detail_qs = SourceRecord.objects.filter(
                    provider=Provider.DEMOCRACY_WORKS, external_id=f"candidate_detail:{candidate_id}"
                ).order_by("-fetched_at")
                if cutoff:
                    recent = existing_detail_qs.filter(fetched_at__gte=cutoff).first()
                    if recent:
                        skipped += 1
                        continue

                cand: dict[str, Any] = {}
                if not endorsements_only:
                    try:
                        cand = client.get_candidate(candidate_id=candidate_id)
                        fetched += 1
                    except DemocracyWorksError as e:
                        errors += 1
                        if print_errors:
                            self.stdout.write(self.style.WARNING(f"ERR candidate_id={candidate_id} err={e}"))
                        continue
                    except Exception as e:
                        errors += 1
                        if print_errors:
                            self.stdout.write(self.style.WARNING(f"ERR candidate_id={candidate_id} unexpected err={e}"))
                        continue

                    if not isinstance(cand, dict) or not str(cand.get("id") or "").strip():
                        skipped += 1
                        continue

                    _record_dw_source(
                        sync_run=run,
                        external_id=f"candidate_detail:{candidate_id}",
                        payload=cand,
                        normalized_obj=person,
                    )

                    party, party_other = _party_from_affiliations(cand.get("partyAffiliation") or [])
                    if not person.manual_party and party != Party.UNKNOWN and (
                        person.party in {Party.UNKNOWN, ""} or person.party != party
                    ):
                        person.party = party
                        person.party_other = party_other
                        person.save(update_fields=["party", "party_other", "updated_at"])

                    ballotpedia_url = str(cand.get("ballotpediaUrl") or "").strip()
                    if ballotpedia_url:
                        ExternalLink.objects.get_or_create(
                            person=person,
                            kind=ExternalLinkKind.BALLOTPEDIA,
                            url=ballotpedia_url,
                            defaults={"label": "Ballotpedia"},
                        )

                    _apply_candidate_contact(person, cand)

                if with_endorsements or endorsements_only:
                    page = 1
                    while True:
                        batch: list[dict[str, Any]] = []
                        pag = None
                        try:
                            batch, pag = client.list_endorsements_bulk_by_matching_entity(
                                candidate_id=candidate_id, page=page, page_size=endorsements_page_size
                            )
                        except DemocracyWorksError as e:
                            errors += 1
                            if print_errors:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"ERR endorsements candidate_id={candidate_id} page={page} err={e}"
                                    )
                                )
                            break
                        except Exception as e:
                            errors += 1
                            if print_errors:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"ERR endorsements candidate_id={candidate_id} page={page} unexpected err={e}"
                                    )
                                )
                            break

                        payload = {
                            "candidateId": candidate_id,
                            "data": batch,
                            "pagination": {
                                "totalRecordCount": pag.total_record_count if pag else 0,
                                "currentPage": pag.current_page if pag else page,
                                "pageSize": pag.page_size if pag else endorsements_page_size,
                            },
                        }
                        _record_dw_source(
                            sync_run=run,
                            external_id=f"candidate_endorsements:{candidate_id}:p{page}",
                            payload=payload,
                            normalized_obj=person,
                        )
                        endorsements_fetched += 1

                        if not pag:
                            break
                        if pag.current_page * pag.page_size >= pag.total_record_count:
                            break
                        page += 1
                        if endorsements_max_pages and page > endorsements_max_pages:
                            break

                        if sleep_ms:
                            time.sleep(sleep_ms / 1000.0)

                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

                if idx % progress_every == 0:
                    self.stdout.write(
                        f"progress {idx}/{total} fetched={fetched} errors={errors} endorsements_records={endorsements_fetched}"
                    )

                if (fetched + skipped + errors) % 25 == 0:
                    run.stats = {
                        **(run.stats or {}),
                        "fetched": fetched,
                        "skipped": skipped,
                        "errors": errors,
                        "endorsements_records": endorsements_fetched,
                        "already_had_detail": already_had_detail,
                        "progress": f"{idx}/{total}",
                    }
                    run.save(update_fields=["stats", "updated_at"])

            run.stats = {
                **(run.stats or {}),
                "fetched": fetched,
                "skipped": skipped,
                "errors": errors,
                "endorsements_records": endorsements_fetched,
                "already_had_detail": already_had_detail,
                "total": total,
            }
            run.status = SyncStatus.SUCCESS if errors == 0 else SyncStatus.PARTIAL
            run.finished_at = timezone.now()
            run.save(update_fields=["stats", "status", "finished_at", "updated_at"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"dw_candidate_details: fetched={fetched} skipped={skipped} errors={errors} "
                    f"endorsements_records={endorsements_fetched} sync_run={run.public_id.hex}"
                )
            )
        except Exception as exc:
            run.status = SyncStatus.FAILED
            run.error_text = f"Unhandled error: {exc}"
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_text", "finished_at", "updated_at"])
            raise
        finally:
            try:
                signal.signal(signal.SIGINT, old_int)
                signal.signal(signal.SIGTERM, old_term)
            except Exception:
                pass
            cache.delete(lock_key)

