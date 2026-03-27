from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from apps.media.models import is_safe_youtube_url


def extract_youtube_video_id(url: str) -> str | None:
    if not url or not url.strip():
        return None
    u = url.strip()
    if not is_safe_youtube_url(u):
        return None
    try:
        parsed = urlparse(u)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")
    if host in {"youtu.be", "www.youtu.be"}:
        return path.split("/")[0] or None
    if "youtube.com" in host:
        if path.startswith("embed/"):
            seg = path.split("/")
            return seg[1] if len(seg) > 1 else None
        if path.startswith("shorts/"):
            seg = path.split("/")
            return seg[1] if len(seg) > 1 else None
        qs = parse_qs(parsed.query)
        v = (qs.get("v") or [None])[0]
        return v or None
    return None
