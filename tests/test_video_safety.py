import pytest

from apps.media.models import VideoEmbed, VideoProvider, is_safe_youtube_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=aaaaaaaaaaa", True),
        ("https://youtu.be/aaaaaaaaaaa", True),
        ("http://m.youtube.com/watch?v=aaaaaaaaaaa", True),
        ("javascript:alert(1)", False),
        ("data:text/html;base64,abc", False),
        ("https://evil.example.com/watch?v=aaaaaaaaaaa", False),
    ],
)
def test_safe_youtube_url(url, expected):
    assert is_safe_youtube_url(url) is expected


def test_video_embed_url_uses_nocookie(db):
    v = VideoEmbed(provider=VideoProvider.YOUTUBE, provider_video_id="aaaaaaaaaaa")
    assert "youtube-nocookie.com/embed/aaaaaaaaaaa" in v.embed_url

