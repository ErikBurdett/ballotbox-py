from __future__ import annotations

import hashlib
import json
from datetime import datetime
from dataclasses import dataclass
from html.parser import HTMLParser
import re
import time
from typing import Any
from urllib.parse import urlencode
from urllib.parse import unquote, urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BallotpediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class BallotpediaHeadshotResult:
    ballotpedia_url: str
    image_url: str
    method: str
    html_sha256: str
    fetched_bytes: int


class _HeadshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_image: str = ""
        self.twitter_image: str = ""
        self.first_img: str = ""
        self.infobox_img: str = ""
        self.infobox_alt: str = ""
        self.all_imgs: list[tuple[str, str]] = []
        self._in_infobox_person: bool = False
        self._infobox_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}

        if tag.lower() in {"table", "div"}:
            cls = (a.get("class") or "").lower()
            if "infobox-person" in cls or "infobox" in cls and "person" in cls:
                self._in_infobox_person = True
                self._infobox_depth = 1
            elif self._in_infobox_person and tag.lower() in {"table", "div"}:
                self._infobox_depth += 1

        if tag.lower() == "meta":
            prop = (a.get("property") or a.get("name") or "").strip().lower()
            content = (a.get("content") or "").strip()
            if not content:
                return
            if prop == "og:image" and not self.og_image:
                self.og_image = content
            if prop in {"twitter:image", "twitter:image:src"} and not self.twitter_image:
                self.twitter_image = content
            return

        if tag.lower() == "img" and not self.first_img:
            src = (a.get("src") or "").strip()
            if src:
                self.first_img = src

        if tag.lower() == "img" and self._in_infobox_person and not self.infobox_img:
            # MediaWiki often uses data-src for lazy-loaded thumbnails.
            src = (a.get("data-src") or a.get("src") or "").strip()
            if src:
                self.infobox_img = src
                self.infobox_alt = (a.get("alt") or "").strip()

        if tag.lower() == "img" and len(self.all_imgs) < 250:
            src = (a.get("data-src") or a.get("src") or "").strip()
            if src:
                self.all_imgs.append((src, (a.get("alt") or "").strip()))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"table", "div"} and self._in_infobox_person:
            self._infobox_depth = max(0, self._infobox_depth - 1)
            if self._infobox_depth == 0:
                self._in_infobox_person = False


def _looks_like_real_headshot(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    u = raw.lower()
    # Ballotpedia often sets og:image to an SVG logo; avoid using it as a headshot.
    try:
        parsed = urlparse(raw)
        path = (parsed.path or "").lower()
    except Exception:
        path = ""
    if path.endswith(".svg"):
        return False
    if "bp-logo" in u or "ballotpedia-logo" in u:
        return False
    if "submitphoto" in u:
        return False
    # Avoid flags and other civic-symbol assets that frequently appear on Texas pages.
    if "flag_of_" in u or "flag-of-" in u:
        return False
    # Skip common non-headshot assets.
    if any(
        token in u
        for token in (
            "candidate_connection",
            "election_coverage_badge",
            "ballotpedia_rss",
            "seal_of_",
            "ballotpedia-election-coverage-badge",
        )
    ):
        return False
    # Prefer common image extensions.
    if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return True
    return False


def _slug_from_ballotpedia_url(url: str) -> str:
    try:
        path = urlparse((url or "").strip()).path or ""
    except Exception:
        return ""
    seg = path.rsplit("/", 1)[-1].strip()
    return unquote(seg)


def _score_candidate(image_url: str, slug: str) -> int:
    u = (image_url or "").lower()
    s = (slug or "").lower()
    score = 0
    # Token match (handles Ballotpedia slugs like Greg_Abbott vs image filenames like GregAbbott2015.jpg)
    tokens = [t for t in s.replace("_", " ").replace("-", " ").split() if t]
    if tokens:
        for t in tokens[:4]:
            if t in u:
                score += 18
    if s and s in u:
        score += 25
    # Prefer Ballotpedia thumbnail store (often headshots).
    if "ballotpedia-api4/files" in u:
        score += 40
    # Prefer larger thumbnails (heuristic).
    if "/thumbs/200/300/" in u or "/thumbs/300/450/" in u:
        score += 10
    if "/thumbs/100/100/" in u:
        score += 3
    # Penalize likely UI assets.
    if "logo" in u or "badge" in u or "icon" in u:
        score -= 15
    return score


def _slug_tokens(slug: str) -> list[str]:
    s = (slug or "").lower().strip()
    if not s:
        return []
    raw = s.replace("_", " ").replace("-", " ")
    tokens = [t.strip() for t in raw.split() if t.strip()]
    # Avoid extremely short tokens; they match too broadly.
    tokens = [t for t in tokens if len(t) >= 3]
    return tokens[:6]


def _token_match_count(text: str, tokens: list[str]) -> int:
    t = (text or "").lower()
    if not t or not tokens:
        return 0
    return sum(1 for tok in tokens if tok in t)


class BallotpediaClient:
    """
    Best-effort HTML fetch + metadata parsing for Ballotpedia profile headshots.

    This intentionally avoids heavy scraping and primarily relies on standard meta tags
    like `og:image` that Ballotpedia commonly includes.
    """

    def __init__(self, *, timeout_s: int = 30, user_agent: str | None = None):
        self.timeout_s = timeout_s
        # Use a mainstream browser UA. Ballotpedia is behind WAF and will sometimes
        # serve bot-challenge pages to non-browser user agents.
        self.user_agent = user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )

    @staticmethod
    def is_allowed_ballotpedia_url(url: str) -> bool:
        try:
            p = urlparse((url or "").strip())
        except Exception:
            return False
        if p.scheme not in {"http", "https"}:
            return False
        host = (p.hostname or "").lower()
        if host == "ballotpedia.org" or host.endswith(".ballotpedia.org"):
            return True
        return False

    def fetch_html(self, url: str) -> str:
        if not self.is_allowed_ballotpedia_url(url):
            raise BallotpediaError("URL is not an allowed ballotpedia.org URL.")

        req = Request(
            url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "upgrade-insecure-requests": "1",
                "user-agent": self.user_agent,
            },
            method="GET",
        )
        last_exc: Exception | None = None
        for attempt in range(3):
            status: int | None = None
            raw: bytes = b""
            try:
                with urlopen(req, timeout=self.timeout_s) as resp:
                    try:
                        status = int(getattr(resp, "status", None) or resp.getcode() or 0) or None
                    except Exception:
                        status = None
                    raw = resp.read()
            except HTTPError as exc:
                # Some non-2xx responses still include HTML; capture it for WAF detection.
                status = int(getattr(exc, "code", None) or 0) or None
                try:
                    raw = exc.read() or b""
                except Exception:
                    raw = b""
                # Retry some transient errors.
                if status in {429, 503, 502} and attempt < 2:
                    time.sleep(0.75 * (attempt + 1))
                    continue
            except (TimeoutError, URLError) as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise BallotpediaError(f"Ballotpedia request failed: {url}") from exc
            except BallotpediaError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise BallotpediaError(f"Ballotpedia request failed: {url}") from exc

            # Best-effort decode; Ballotpedia pages are typically UTF-8.
            html = (raw or b"").decode("utf-8", "ignore")
            low = html.lower()
            # Detect AWS WAF / bot challenge responses (these are not the real page content).
            if "awswafcookiedomainlist" in low or "gokuprops" in low or "aws waf" in low:
                raise BallotpediaError("Ballotpedia returned a bot challenge page (AWS WAF).")

            if status and status >= 400:
                # Treat 404/410 as "no page" rather than WAF.
                # Retry some transient errors.
                if status in {429, 503, 502} and attempt < 2:
                    time.sleep(0.75 * (attempt + 1))
                    continue
                raise BallotpediaError(f"Ballotpedia HTTP {status}: {url}")

            return html

        raise BallotpediaError(f"Ballotpedia request failed: {url}") from last_exc

    def extract_headshot(self, *, ballotpedia_url: str, html: str) -> BallotpediaHeadshotResult | None:
        parser = _HeadshotParser()
        parser.feed(html)
        parser.close()

        slug = _slug_from_ballotpedia_url(ballotpedia_url)
        tokens = _slug_tokens(slug)

        candidates: list[tuple[str, str, str]] = []
        if parser.infobox_img:
            candidates.append(("infobox_img", parser.infobox_img, parser.infobox_alt))
        if parser.og_image:
            candidates.append(("og:image", parser.og_image, ""))
        if parser.twitter_image:
            candidates.append(("twitter:image", parser.twitter_image, ""))
        if parser.first_img:
            candidates.append(("first_img", parser.first_img, ""))
        # Many Ballotpedia person pages don't surface a headshot in the infobox/meta,
        # but do include it as an <img> elsewhere. We'll consider <img> tags, but only
        # when the image appears to match the page slug (prevents "wrong person" picks).
        for src, alt in parser.all_imgs:
            candidates.append(("img_tag", src, alt))

        resolved_candidates: list[tuple[int, str, str]] = []
        last_token = tokens[-1] if tokens else ""
        for method, raw_url, alt in candidates:
            resolved = urljoin(ballotpedia_url, raw_url)
            if not resolved or not resolved.startswith(("http://", "https://")):
                continue
            if not _looks_like_real_headshot(resolved):
                continue
            score = _score_candidate(resolved, slug)
            url_token_hits = _token_match_count(resolved, tokens)
            alt_token_hits = _token_match_count(alt, tokens)

            # Token alignment rules:
            # - infobox/meta sources are usually safe; don't require tokens.
            # - img_tag sources must match tokens (prevents unrelated images).
            if method == "img_tag":
                combined_hits = url_token_hits + alt_token_hits
                # Require at least some match, and strongly prefer the last-name token.
                last_name_hit = (last_token in (resolved.lower() + " " + (alt or "").lower())) if last_token else False
                if combined_hits == 0:
                    continue
                if len(tokens) >= 2 and not (last_name_hit or combined_hits >= 2):
                    continue

            # Minimum confidence thresholds (balanced).
            if method == "infobox_img":
                # The infobox image (when present) is usually the canonical headshot.
                # Be permissive here; we already filter obvious non-headshot assets.
                score += 25  # prefer infobox when present
            elif method in {"og:image", "twitter:image", "first_img"}:
                if score < 35:
                    continue
            else:  # img_tag
                if score < 55:
                    continue

            # If tokens match, bump slightly (helps disambiguate multiple images).
            score += min(10, (url_token_hits + alt_token_hits) * 3)
            resolved_candidates.append((score, method, resolved))

        if resolved_candidates:
            resolved_candidates.sort(key=lambda t: (-t[0], t[1]))
            _score, method, image_url = resolved_candidates[0]
            image_url = self.upgrade_image_url(image_url)
            sha = hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()
            return BallotpediaHeadshotResult(
                ballotpedia_url=ballotpedia_url,
                image_url=image_url,
                method=method,
                html_sha256=sha,
                fetched_bytes=len(html.encode("utf-8", "ignore")),
            )
        return None

    def upgrade_image_url(self, url: str) -> str:
        """
        Prefer a higher-quality/original image URL when we recognize a thumbnail pattern.

        - ballotpedia-api4 thumbs: /files/thumbs/W/H/FILENAME -> /files/FILENAME
        - ballotpedia mediawiki thumbs: /images/thumb/.../NNpx-FILENAME -> /images/.../FILENAME
        """
        u = (url or "").strip()
        if not u.startswith(("http://", "https://")):
            return u
        candidates: list[str] = []

        low = u.lower()
        if "s3.amazonaws.com/ballotpedia-api4/files/thumbs/" in low:
            # https://s3.amazonaws.com/ballotpedia-api4/files/thumbs/200/300/Foo.jpg
            # -> https://s3.amazonaws.com/ballotpedia-api4/files/Foo.jpg
            try:
                parts = u.split("/files/thumbs/", 1)
                tail = parts[1].split("/", 2)[-1]  # drop W/H
                candidates.append(parts[0] + "/files/" + tail)
            except Exception:
                pass

        if "ballotpedia.s3.amazonaws.com/images/thumb/" in low:
            # https://ballotpedia.s3.amazonaws.com/images/thumb/7/7a/Foo.png/75px-Foo.png
            # -> https://ballotpedia.s3.amazonaws.com/images/7/7a/Foo.png
            try:
                before, after = u.split("/images/thumb/", 1)
                # after: "7/7a/Foo.png/75px-Foo.png"
                path_parts = after.split("/")
                if len(path_parts) >= 4:
                    orig_rel = "/".join(path_parts[:3])  # 7/7a/Foo.png
                    candidates.append(before + "/images/" + orig_rel)
            except Exception:
                pass

        # Prefer the first candidate that actually resolves to an image.
        for cand in candidates:
            if cand != u and self._probe_image_url(cand):
                return cand
        return u

    def _mediawiki_api_image(self, ballotpedia_url: str) -> str:
        slug = _slug_from_ballotpedia_url(ballotpedia_url)
        if not slug:
            return ""

        def _api_json(params: dict[str, str]) -> dict[str, Any]:
            api_url = "https://ballotpedia.org/api.php"
            req = Request(
                f"{api_url}?{urlencode(params)}",
                headers={
                    "accept": "application/json",
                    "accept-language": "en-US,en;q=0.9",
                    "cache-control": "no-cache",
                    "pragma": "no-cache",
                    "user-agent": self.user_agent,
                },
                method="GET",
            )
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    with urlopen(req, timeout=min(self.timeout_s, 12)) as resp:
                        raw = resp.read()
                    return json.loads((raw or b"{}").decode("utf-8", "ignore"))
                except HTTPError as exc:
                    last_exc = exc
                    status = int(getattr(exc, "code", None) or 0) or None
                    if status in {429, 500, 502, 503, 504} and attempt < 2:
                        time.sleep(0.75 * (attempt + 1))
                        continue
                    return {}
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise BallotpediaError("Ballotpedia MediaWiki API request failed.") from last_exc
            return {}

        # 1) List images used on the page.
        payload = _api_json(
            {
                "action": "query",
                "format": "json",
                "redirects": "1",
                "prop": "images",
                "imlimit": "50",
                "titles": slug,
            }
        )
        pages = (((payload or {}).get("query") or {}).get("pages") or {})
        if not isinstance(pages, dict) or not pages:
            return ""
        page = None
        for _k, v in pages.items():
            if isinstance(v, dict):
                page = v
                break
        if not page:
            return ""
        images = page.get("images") if isinstance(page.get("images"), list) else []
        if not images:
            return ""

        # 2) Pick likely headshot file titles, then resolve to URLs via imageinfo.
        candidates: list[tuple[int, str]] = []
        bad_tokens = (
            "flag_of_",
            "seal_of_",
            "logo",
            "badge",
            "map",
            "district",
            "county",
            "city",
        )
        for img in images:
            title = str(img.get("title") or "").strip() if isinstance(img, dict) else ""
            if not title.lower().startswith("file:"):
                continue
            low = title.lower()
            if any(t in low for t in bad_tokens):
                continue
            score = _score_candidate(title, slug)
            candidates.append((score, title))

        candidates.sort(key=lambda t: -t[0])
        for _score, title in candidates[:8]:
            info = _api_json(
                {
                    "action": "query",
                    "format": "json",
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "titles": title,
                }
            )
            pages2 = (((info or {}).get("query") or {}).get("pages") or {})
            if not isinstance(pages2, dict) or not pages2:
                continue
            page2 = None
            for _k2, v2 in pages2.items():
                if isinstance(v2, dict):
                    page2 = v2
                    break
            if not page2:
                continue
            ii = page2.get("imageinfo") if isinstance(page2.get("imageinfo"), list) else []
            if not ii:
                continue
            url = str((ii[0] or {}).get("url") or "").strip() if isinstance(ii[0], dict) else ""
            if not url:
                continue
            if _looks_like_real_headshot(url):
                return url
        return ""

    def get_headshot_via_api(self, ballotpedia_url: str) -> BallotpediaHeadshotResult | None:
        try:
            image_url = self._mediawiki_api_image(ballotpedia_url)
        except Exception:
            image_url = ""
        image_url = self.upgrade_image_url(image_url)
        if image_url and _looks_like_real_headshot(image_url):
            return BallotpediaHeadshotResult(
                ballotpedia_url=ballotpedia_url,
                image_url=image_url,
                method="mediawiki_api",
                html_sha256="",
                fetched_bytes=0,
            )
        return None

    def _probe_image_url(self, url: str) -> bool:
        """
        Best-effort existence check for an image URL.

        Uses a 1-byte Range request when supported to minimize bandwidth.
        """
        u = (url or "").strip()
        if not u.startswith(("http://", "https://")):
            return False
        headers = {
            "accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "user-agent": self.user_agent,
        }
        # This is used in tight loops during bulk syncs; keep it very short.
        # Public S3 thumb URLs either exist and respond quickly, or they don't.
        timeout = min(self.timeout_s, 3)
        # Prefer HEAD (fast). For Ballotpedia's S3 thumbs, HEAD is supported and much cheaper
        # than opening a GET connection repeatedly during bulk runs.
        try:
            host = (urlparse(u).hostname or "").lower()
        except Exception:
            host = ""
        methods = [("HEAD", {})] if "s3.amazonaws.com" in host else [("HEAD", {}), ("GET", {"range": "bytes=0-0"})]

        for method, extra_headers in methods:
            req = Request(u, headers={**headers, **extra_headers}, method=method)
            try:
                with urlopen(req, timeout=timeout) as resp:
                    ctype = str(resp.headers.get("content-type") or "").lower()
                    if not ctype.startswith("image/"):
                        continue
                    return True
            except Exception:
                continue
        return False

    def _guess_s3_headshot(self, ballotpedia_url: str) -> BallotpediaHeadshotResult | None:
        """
        Fallback for pages blocked by AWS WAF.

        Many Ballotpedia headshots are hosted on a public S3 bucket with predictable filenames.
        This tries a conservative set of likely filenames derived from the profile slug.
        """
        slug = _slug_from_ballotpedia_url(ballotpedia_url)
        if not slug:
            return None
        seg = slug.strip()
        seg_no_qual = re.split(r"\(", seg, maxsplit=1)[0].rstrip(" _-")
        seg_no_punct = seg_no_qual.replace("’", "").replace("'", "").replace(",", "").replace(".", "")

        bases: list[str] = []
        for v in [seg_no_qual, seg_no_punct]:
            vv = (v or "").strip().strip(" _-")
            if not vv:
                continue
            bases.append(vv)
            if "_" in vv:
                bases.append(vv.replace("_", "-"))
        # De-dupe while preserving order.
        seen_b: set[str] = set()
        bases2: list[str] = []
        for b in bases:
            if b and b not in seen_b:
                seen_b.add(b)
                bases2.append(b)
        bases = bases2[:4]

        yy = datetime.utcnow().year % 100
        filenames: list[str] = []
        for base in bases:
            for ext in (".jpg", ".png", ".jpeg"):
                filenames.append(f"{base}{ext}")
                filenames.append(f"{base}_{yy:02d}{ext}")

        # Probe the original file URL directly (fewer requests than thumbs + upgrades).
        probes = 0
        max_probes = 10
        for filename in filenames:
            probes += 1
            if probes > max_probes:
                return None
            candidate = f"https://s3.amazonaws.com/ballotpedia-api4/files/{filename}"
            if not _looks_like_real_headshot(candidate):
                continue
            if self._probe_image_url(candidate):
                return BallotpediaHeadshotResult(
                    ballotpedia_url=ballotpedia_url,
                    image_url=candidate,
                    method="s3_guess",
                    html_sha256="",
                    fetched_bytes=0,
                )
        return None

    def guess_headshot(self, ballotpedia_url: str) -> BallotpediaHeadshotResult | None:
        """
        Public wrapper for the fast S3 headshot guessing fallback.
        """
        return self._guess_s3_headshot(ballotpedia_url)

    def get_headshot(self, ballotpedia_url: str) -> BallotpediaHeadshotResult | None:
        # Fast path: probe the most common public S3 headshot URLs.
        guessed = self._guess_s3_headshot(ballotpedia_url)
        if guessed:
            return guessed

        try:
            html = self.fetch_html(ballotpedia_url)
        except BallotpediaError as exc:
            msg = str(exc).lower()
            if "aws waf" in msg or "bot challenge" in msg:
                return None
            if "http 404" in msg or "http 410" in msg:
                return None
            raise
        extracted = self.extract_headshot(ballotpedia_url=ballotpedia_url, html=html)
        if extracted:
            return extracted
        return None

