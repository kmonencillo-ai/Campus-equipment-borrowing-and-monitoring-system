from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        content_security_policy = getattr(settings, 'SECURITY_CONTENT_SECURITY_POLICY', '').strip()
        permissions_policy = getattr(settings, 'SECURITY_PERMISSIONS_POLICY', '').strip()

        if content_security_policy and 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = content_security_policy
        if permissions_policy and 'Permissions-Policy' not in response:
            response['Permissions-Policy'] = permissions_policy
        if 'X-Permitted-Cross-Domain-Policies' not in response:
            response['X-Permitted-Cross-Domain-Policies'] = 'none'

        return response


class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            timeout_seconds = max(int(getattr(settings, 'SESSION_IDLE_TIMEOUT', 0)), 0)
            current_timestamp = int(timezone.now().timestamp())
            last_activity = request.session.get('last_activity')

            login_path = getattr(settings, 'LOGIN_URL', '/login/')
            exempt_paths = {
                login_path,
                getattr(settings, 'LOGOUT_REDIRECT_URL', '/login/'),
                '/logout/',
                '/health/',
            }

            is_password_reset_path = request.path.startswith('/password-reset')
            is_static_path = request.path.startswith(getattr(settings, 'STATIC_URL', '/static/'))
            is_exempt = request.path in exempt_paths or is_password_reset_path or is_static_path

            if timeout_seconds and last_activity and current_timestamp - last_activity > timeout_seconds and not is_exempt:
                logout(request)
                messages.error(request, "You were logged out automatically because your session was inactive for too long.")
                return redirect('login')

            if not is_exempt:
                request.session['last_activity'] = current_timestamp

        return self.get_response(request)
