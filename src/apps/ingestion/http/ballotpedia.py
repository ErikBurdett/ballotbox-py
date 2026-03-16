from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
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
        self.all_imgs: list[str] = []
        self._in_infobox_person: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}

        if tag.lower() == "table":
            cls = (a.get("class") or "").lower()
            if "infobox-person" in cls or "infobox" in cls and "person" in cls:
                self._in_infobox_person = True

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

        if tag.lower() == "img" and len(self.all_imgs) < 250:
            src = (a.get("data-src") or a.get("src") or "").strip()
            if src:
                self.all_imgs.append(src)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "table" and self._in_infobox_person:
            self._in_infobox_person = False


def _looks_like_real_headshot(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    # Ballotpedia often sets og:image to an SVG logo; avoid using it as a headshot.
    if u.endswith(".svg"):
        return False
    if "bp-logo" in u or "ballotpedia-logo" in u:
        return False
    if "submitphoto" in u:
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
    if u.endswith((".jpg", ".jpeg", ".png", ".webp")):
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


class BallotpediaClient:
    """
    Best-effort HTML fetch + metadata parsing for Ballotpedia profile headshots.

    This intentionally avoids heavy scraping and primarily relies on standard meta tags
    like `og:image` that Ballotpedia commonly includes.
    """

    def __init__(self, *, timeout_s: int = 30, user_agent: str | None = None):
        self.timeout_s = timeout_s
        self.user_agent = user_agent or "the-ballot-box/0.1 (+https://example.invalid)"

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
                "accept": "text/html,application/xhtml+xml",
                "user-agent": self.user_agent,
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
                # Best-effort decode; Ballotpedia pages are typically UTF-8.
                return raw.decode("utf-8", "ignore")
        except Exception as exc:
            raise BallotpediaError(f"Ballotpedia request failed: {url}") from exc

    def extract_headshot(self, *, ballotpedia_url: str, html: str) -> BallotpediaHeadshotResult | None:
        parser = _HeadshotParser()
        parser.feed(html)
        parser.close()

        slug = _slug_from_ballotpedia_url(ballotpedia_url)

        candidates: list[tuple[str, str]] = []
        if parser.infobox_img:
            candidates.append(("infobox_img", parser.infobox_img))
        if parser.og_image:
            candidates.append(("og:image", parser.og_image))
        if parser.twitter_image:
            candidates.append(("twitter:image", parser.twitter_image))
        if parser.first_img:
            candidates.append(("first_img", parser.first_img))
        for src in parser.all_imgs:
            candidates.append(("img_tag", src))

        resolved_candidates: list[tuple[int, str, str]] = []
        for method, raw_url in candidates:
            resolved = urljoin(ballotpedia_url, raw_url)
            if not resolved or not resolved.startswith(("http://", "https://")):
                continue
            if not _looks_like_real_headshot(resolved):
                continue
            resolved_candidates.append((_score_candidate(resolved, slug), method, resolved))

        if resolved_candidates:
            resolved_candidates.sort(key=lambda t: (-t[0], t[1]))
            _score, method, image_url = resolved_candidates[0]
            sha = hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()
            return BallotpediaHeadshotResult(
                ballotpedia_url=ballotpedia_url,
                image_url=image_url,
                method=method,
                html_sha256=sha,
                fetched_bytes=len(html.encode("utf-8", "ignore")),
            )
        return None

    def get_headshot(self, ballotpedia_url: str) -> BallotpediaHeadshotResult | None:
        html = self.fetch_html(ballotpedia_url)
        return self.extract_headshot(ballotpedia_url=ballotpedia_url, html=html)

