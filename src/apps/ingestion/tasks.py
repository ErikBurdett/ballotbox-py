from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.core.management import call_command
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.people.models import Person

from .adapters.registry import get_adapters
from .models import MergeReview, MergeStatus, Provider, SyncRun, SyncStatus


logger = logging.getLogger(__name__)

def _lock_key(provider: str) -> str:
    return f"lock:sync:{provider}"


@shared_task
def sync_provider(provider: str) -> str:
    provider_value = provider
    # Prevent overlapping runs of the same provider.
    lock_key = _lock_key(provider_value)
    if not cache.add(lock_key, "1", timeout=60 * 60):
        run = SyncRun.objects.create(provider=provider_value, status=SyncStatus.CANCELLED)
        run.error_text = "Another sync run for this provider is already in progress."
        run.finished_at = timezone.now()
        run.save(update_fields=["error_text", "finished_at", "updated_at"])
        return run.public_id.hex

    run = SyncRun.objects.create(provider=provider_value, status=SyncStatus.RUNNING)

    try:
        from django.conf import settings as django_settings

        if provider_value == Provider.DEMOCRACY_WORKS and not (
            getattr(django_settings, "DEMOCRACY_WORKS_API_KEY", "") or ""
        ).strip():
            run.status = SyncStatus.SUCCESS
            run.stats = {"fetched": 0, "skipped": True}
            run.error_text = (
                "Skipped: DEMOCRACY_WORKS_API_KEY is not set. Existing Democracy Works data is unchanged; "
                "use Ballotpedia geographic sync for new election data."
            )
            return run.public_id.hex

        adapters = [a for a in get_adapters() if a.provider == provider_value]
        if not adapters:
            run.status = SyncStatus.FAILED
            run.error_text = f"No adapter registered for provider={provider_value}"
            return run.public_id.hex

        adapter = adapters[0]
        fetched = 0
        errors = 0

        # Prefer streaming fetches for large providers (e.g. Democracy Works state backfills).
        payload_iter = None
        if hasattr(adapter, "fetch_iter"):
            try:
                payload_iter = adapter.fetch_iter()
            except Exception as exc:
                run.status = SyncStatus.FAILED
                run.error_text = f"Fetch failed for provider={provider_value}: {exc}"
                run.stats = {"fetched": 0, "errors": 1}
                return run.public_id.hex
            run.stats = {"fetched": 0}
            run.save(update_fields=["stats", "updated_at"])
        else:
            try:
                payloads = adapter.fetch()
            except Exception as exc:
                run.status = SyncStatus.FAILED
                run.error_text = f"Fetch failed for provider={provider_value}: {exc}"
                run.stats = {"fetched": 0, "errors": 1}
                return run.public_id.hex
            if provider_value == Provider.DEMOCRACY_WORKS and not payloads:
                run.status = SyncStatus.FAILED
                run.error_text = (
                    "No DW sync scope configured. Set DEMOCRACY_WORKS_STATE_CODE, "
                    "full DEMOCRACY_WORKS_ADDRESS_* values, or DEMOCRACY_WORKS_AMARILLO_METRO=true "
                    "(or run manage.py sync_democracy_works --amarillo-metro)."
                )
                run.stats = {"fetched": 0, "errors": 0}
                return run.public_id.hex
            payload_iter = iter(payloads)
            run.stats = {"fetched": len(payloads)}
            run.save(update_fields=["stats", "updated_at"])

        try:
            for payload in payload_iter or []:
                fetched += 1
                try:
                    adapter.normalize(payload, sync_run=run)
                except Exception as exc:
                    errors += 1
                    logger.exception("normalize failed provider=%s", provider_value)
                    run.error_text = (run.error_text + "\n" if run.error_text else "") + str(exc)
                if fetched and fetched % 25 == 0:
                    run.stats = {**(run.stats or {}), "fetched": fetched, "errors": errors}
                    run.save(update_fields=["stats", "updated_at"])
        except Exception as exc:
            # Catch fetch/iteration exceptions (e.g. upstream HTTP 429) so the SyncRun is not left RUNNING forever.
            errors += 1
            logger.exception("fetch/iterate failed provider=%s", provider_value)
            run.status = SyncStatus.FAILED
            run.error_text = (run.error_text + "\n" if run.error_text else "") + f"Fetch failed: {exc}"
            run.stats = {**(run.stats or {}), "fetched": fetched, "errors": errors}
            return run.public_id.hex

        if provider_value == Provider.DEMOCRACY_WORKS and fetched == 0:
            run.status = SyncStatus.FAILED
            run.error_text = (
                "No Democracy Works elections were returned for the configured scope. "
                "Check DEMOCRACY_WORKS_STATE_CODE, address settings, Amarillo metro mode, "
                "and (optionally) DEMOCRACY_WORKS_START_DATE / DEMOCRACY_WORKS_END_DATE."
            )
            run.stats = {"fetched": 0, "errors": 0}
            return run.public_id.hex

        run.stats = {**(run.stats or {}), "fetched": fetched or (run.stats or {}).get("fetched", 0), "errors": errors}
        run.status = SyncStatus.PARTIAL if errors else SyncStatus.SUCCESS
        return run.public_id.hex
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_text", "stats", "finished_at", "updated_at"])
        cache.delete(lock_key)


@shared_task
def sync_all_providers() -> list[str]:
    results: list[str] = []
    for provider, _label in Provider.choices:
        # Democracy Works is expensive and quota-limited; run it explicitly via management commands.
        if provider == Provider.DEMOCRACY_WORKS:
            continue
        results.append(sync_provider(provider))
    return results


@shared_task
def sync_ballotpedia_photos_batch(
    limit: int = 50,
    sleep_ms: int = 250,
    fresh_days: int = 30,
    with_contact: bool = False,
    only_missing_contact: bool = False,
) -> str:
    """
    Incremental Ballotpedia photo enrichment.

    This calls the management command (which creates its own SyncRun + SourceRecords)
    and is intentionally batch-sized to keep the worker responsive.
    """
    lock_key = _lock_key("ballotpedia_photos")
    if not cache.add(lock_key, "1", timeout=60 * 60):
        return "locked"
    try:
        from django.conf import settings
        state = ""
        try:
            state = str((getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}).get("state_code") or "").strip().upper()
        except Exception:
            state = ""
        if not state:
            state = str(getattr(settings, "BALLOTPEDIA_SYNC_STATE_CODE", "") or "").strip().upper()
        if not state:
            state = "TX"
        call_command(
            "sync_ballotpedia_photos",
            limit=limit,
            sleep_ms=sleep_ms,
            fresh_days=fresh_days,
            state=state,
            with_contact=with_contact,
            only_missing_contact=only_missing_contact,
        )
        return "ok"
    finally:
        cache.delete(lock_key)


@shared_task
def sync_ballotpedia_geographic_scheduled() -> str:
    """
    Scheduled Ballotpedia Data Client geographic sync (Potter + Randall by default).

    Quota-friendly defaults come from Django settings (BALLOTPEDIA_GEO_*).
    """
    from django.conf import settings

    if not (getattr(settings, "BALLOTPEDIA_API_KEY", "") or "").strip():
        return "skipped_no_ballotpedia_api_key"
    lock_key = _lock_key("ballotpedia_geographic")
    if not cache.add(lock_key, "1", timeout=60 * 60):
        return "locked"
    try:
        kwargs: dict = {
            "max_requests": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_REQUESTS", 160)),
            "max_election_dates": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_ELECTION_DATES", 14)),
            "max_tx_calendar_pages": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_TX_CALENDAR_PAGES", 10)),
            "tx_local_state_pages": int(getattr(settings, "BALLOTPEDIA_GEO_TX_LOCAL_STATE_PAGES", 1)),
            "skip_if_fetched_days": int(getattr(settings, "BALLOTPEDIA_GEO_SKIP_IF_FETCHED_DAYS", 1)),
        }
        if bool(getattr(settings, "BALLOTPEDIA_GEO_WITH_OFFICEHOLDERS", False)):
            kwargs["with_officeholders"] = True
        call_command("sync_ballotpedia_geographic", **kwargs)
        return "ok"
    finally:
        cache.delete(lock_key)


@shared_task
def detect_person_duplicates(max_groups: int = 50) -> int:
    """
    Very conservative duplicate detection: same first+last (case-insensitive).
    Creates MergeReview records for human review.
    """
    ct = ContentType.objects.get_for_model(Person)
    groups = (
        Person.objects.exclude(first_name="")
        .exclude(last_name="")
        .values("first_name", "last_name")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("-n")[:max_groups]
    )

    created = 0
    for g in groups:
        people = list(
            Person.objects.filter(first_name=g["first_name"], last_name=g["last_name"]).order_by("id")[:5]
        )
        if len(people) < 2:
            continue
        a = people[0]
        for b in people[1:]:
            exists = MergeReview.objects.filter(
                status=MergeStatus.OPEN,
                candidate_a_content_type=ct,
                candidate_a_object_id=a.id,
                candidate_b_content_type=ct,
                candidate_b_object_id=b.id,
            ).exists()
            if exists:
                continue
            MergeReview.objects.create(
                candidate_a_content_type=ct,
                candidate_a_object_id=a.id,
                candidate_b_content_type=ct,
                candidate_b_object_id=b.id,
                merge_reason=f"Auto-detected potential duplicate: {a.display_name}",
            )
            created += 1

    return created

