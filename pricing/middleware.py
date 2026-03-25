"""
Middleware: LoginRequiredMiddleware — enforce authentication on all pricing views.
"""

from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """
    Redirect anonymous users to login for all paths except exempted ones.

    Exempt paths: LOGIN_URL, /logout/, /admin/, /static/, /agent/ (public token pages).
    Superusers pass through with no org restrictions.
    """

    EXEMPT_PREFIXES = [
        settings.LOGIN_URL,
        '/logout/',
        '/admin/',
        '/static/',
        '/agent/',   # Public token-based agent rate cards
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_anonymous:
            path = request.path
            if not any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
                login_url = settings.LOGIN_URL
                return redirect(f'{login_url}?next={path}')
        return self.get_response(request)
