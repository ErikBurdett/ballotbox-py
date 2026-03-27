from __future__ import annotations

from django.conf import settings


def site_defaults(request):
    return {
        "SITE_NAME": "The Ballot Box",
        "SITE_TAGLINE": "Trustworthy, source-attributed directories for officials and candidates.",
        "CONTACT_EMAIL": "info@patriotsinaction.com",
        "DEBUG": bool(settings.DEBUG),
    }

