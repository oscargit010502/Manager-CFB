from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter
from core.documents import validate_pdf, MAX_PDF_BYTES
from core.models import LoginAttempt


def pdf_file():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return SimpleUploadedFile('documento.pdf', output.getvalue(), content_type='application/pdf')


class UploadValidationTests(SimpleTestCase):
    def test_valid_pdf_checksum_and_pointer(self):
        file = pdf_file()
        result = validate_pdf(file)
        self.assertEqual(result['size'], file.size)
        self.assertEqual(len(result['sha256']), 64)
        self.assertEqual(file.tell(), 0)

    def test_fake_pdf_mime_extension_and_empty_are_rejected(self):
        for name, data in [('falso.pdf', b'<html>fake</html>'), ('vacio.pdf', b''), ('archivo.html', b'%PDF-1.7 fake')]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_pdf(SimpleUploadedFile(name, data, content_type='application/pdf'))

    def test_truncated_oversized_and_encrypted_pdf_are_rejected(self):
        file = pdf_file()
        file.size = MAX_PDF_BYTES + 1
        with self.assertRaises(ValidationError):
            validate_pdf(file)
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile('roto.pdf', b'%PDF-1.7\ninvalid'))
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('test-only')
        writer.write(output)
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile('cifrado.pdf', output.getvalue()))

    def test_pdf_javascript_rejected(self):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_js('app.alert("unsafe")')
        writer.write(output)
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile('activo.pdf', output.getvalue()))


@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('pruebas', password='password-test-only-1998')

    def test_anonymous_private_routes_redirect(self):
        for route in ('dashboard', 'case_list', 'case_create', 'company_settings'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)
        self.assertEqual(self.client.get('/media/documents/test.pdf').status_code, 404)

    def test_authenticated_unassigned_user_cannot_read_cases(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('case_list')).status_code, 403)

    def test_login_throttle_and_expiry(self):
        for _ in range(10):
            response = self.client.post(reverse('login'), {'username':'pruebas', 'password':'incorrecta'})
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('login'), {'username':'pruebas', 'password':'password-test-only-1998'})
        self.assertEqual(response.status_code, 429)
        LoginAttempt.objects.update(last_attempt=timezone.now() - timedelta(minutes=16))
        response = self.client.post(reverse('login'), {'username':'pruebas', 'password':'password-test-only-1998'})
        self.assertEqual(response.status_code, 302)

    def test_login_requires_csrf_and_admin_uses_throttle(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('login'), {'username':'pruebas','password':'password-test-only-1998'}).status_code, 403)
        for _ in range(10):
            self.client.post('/admin/login/', {'username':'pruebas', 'password':'incorrecta'})
        self.assertEqual(self.client.post('/admin/login/', {'username':'pruebas','password':'incorrecta'}).status_code, 429)

    def test_logout_post_and_no_external_login_redirect(self):
        response = self.client.post(reverse('login'), {'username':'pruebas','password':'password-test-only-1998','next':'https://evil.example/'})
        self.assertEqual(response.url, '/')
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)

    def test_private_cache_and_security_headers(self):
        response = self.client.get(reverse('login'))
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn("object-src 'none'", response['Content-Security-Policy'])
