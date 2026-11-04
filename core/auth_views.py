from datetime import timedelta
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import LoginAttempt

class PrivateLoginView(LoginView):
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.path.startswith('/admin/') and request.user.is_authenticated and not request.user.is_staff:
            raise PermissionDenied('La administración de usuarios requiere acceso administrativo.')
        return super().dispatch(request, *args, **kwargs)

    def _keys(self):
        username = self.request.POST.get('username', '').strip().casefold()[:150]
        address = self.request.META.get('REMOTE_ADDR', '')
        return [salted_hmac('cfb-login', item).hexdigest() for item in ('user:' + username, 'ip:' + address)]

    def post(self, request, *args, **kwargs):
        cutoff = timezone.now() - timedelta(minutes=15)
        if LoginAttempt.objects.filter(key__in=self._keys(), failures__gte=10, last_attempt__gte=cutoff).exists():
            form = self.get_form()
            form.is_valid()
            form.add_error(None, 'Demasiados intentos. Espere 15 minutos antes de volver a ingresar.')
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        with transaction.atomic():
            now = timezone.now()
            LoginAttempt.objects.filter(last_attempt__lt=now - timedelta(days=1)).delete()
            for key in self._keys():
                attempt, _ = LoginAttempt.objects.select_for_update().get_or_create(key=key)
                if attempt.last_attempt < now - timedelta(minutes=15):
                    attempt.failures = 0
                attempt.failures += 1
                attempt.last_attempt = now
                attempt.save()
        return super().form_invalid(form)

    def form_valid(self, form):
        LoginAttempt.objects.filter(key=self._keys()[0]).delete()
        return super().form_valid(form)
