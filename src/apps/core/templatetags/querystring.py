from __future__ import annotations

from urllib.parse import urlencode

from django import template


register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **kwargs) -> str:
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = urlencode(params, doseq=True)
    return f"?{encoded}" if encoded else ""

