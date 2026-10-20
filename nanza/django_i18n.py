"""Optional Django adapter; the Tk desktop does not import or require Django."""
from contextvars import ContextVar
from functools import lru_cache
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

_language = ContextVar("nanza_template_language", default="en")


@lru_cache(maxsize=1)
def catalogue():
    return json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))


def translate(value):
    return catalogue().get(_language.get(), catalogue()["en"]).get(str(value), value)


class SessionLanguageMiddleware:
    """Place after SessionMiddleware and LocaleMiddleware in a real Django host."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = request.session.get("django_language", getattr(request, "LANGUAGE_CODE", "en"))
        if language not in ("en", "ar"): language = "en"
        token = _language.set(language)
        previous = getattr(request, "LANGUAGE_CODE", None)
        try:
            request.LANGUAGE_CODE = language
            with translation.override(language):
                return self.get_response(request)
        finally:
            _language.reset(token)
            if previous is None: del request.LANGUAGE_CODE
            else: request.LANGUAGE_CODE = previous


@require_POST
@csrf_protect
def set_language(request):
    language = request.POST.get("language")
    if language not in ("en", "ar"):
        return HttpResponseBadRequest(_("Unsupported language"))
    request.session["django_language"] = language
    target = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        target = "/"
    response = HttpResponseRedirect(target)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, samesite="Lax", secure=request.is_secure())
    return response
