"""
CSRF failure view (settings.CSRF_FAILURE_VIEW).

Django's CsrfViewMiddleware -- and the csrf_protect decorator on the login
views -- answer a failed check with an HTML page. The SPAs only ever speak
JSON, so API paths get a JSON body with the same error shape as every other
refusal; anything else keeps Django's default page.

DRF's SessionAuthentication performs its own CSRF check inside the view and
already answers in JSON, so this only covers the login endpoints.
"""
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request, reason=""):
    if request.path.startswith('/api/'):
        return JsonResponse(
            {
                "error": "CSRF_FAILED",
                "message": "The request could not be verified. Refresh the page and try again.",
            },
            status=403,
        )
    return django_csrf_failure(request, reason=reason)
