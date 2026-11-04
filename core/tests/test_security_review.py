"""Regression coverage from independent authorization/integrity review."""
import io
import tempfile
from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from core.models import Case, Document, DocumentRequirement
from core.documents import validate_pdf


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SecurityReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('review_operator', password='Test-only-secret-2026')
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='core', codename__in=['view_case', 'manage_operations']))
        self.case = Case.objects.create(deceased_name='Persona de prueba', death_date=timezone.localdate(),
            requester_name='Solicitante', payer_type='private', payer_name='Particular', created_by=self.user)
        self.client.force_login(self.user)

    def test_duplicate_requirement_is_rejected_as_form_error(self):
        DocumentRequirement.objects.create(case=self.case, label='Certificado obligatorio')
        response = self.client.post(reverse('requirement_add', args=[self.case.pk]), {
            'label': 'Certificado obligatorio', 'required': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.case.requirements.count(), 1)

    def test_document_cannot_satisfy_another_case_requirement(self):
        second = Case.objects.create(deceased_name='Otra persona de prueba', death_date=timezone.localdate(),
            requester_name='Solicitante', payer_type='private', payer_name='Particular', created_by=self.user)
        requirement = DocumentRequirement.objects.create(case=second, label='Certificado')
        content = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(content)
        with tempfile.TemporaryDirectory() as storage:
            with override_settings(MEDIA_ROOT=storage):
                response = self.client.post(reverse('document_upload', args=[self.case.pk]), {
                    'title': 'Intento de asociación cruzada', 'requirement': requirement.pk,
                    'file': SimpleUploadedFile('documento.pdf', content.getvalue(), content_type='application/pdf')})
                self.assertEqual(response.status_code, 200)
                self.assertIn('requirement', response.context['form'].errors)
                self.assertFalse(Document.objects.exists())
                self.assertEqual(list(Path(storage).rglob('*.pdf')), [])

    def test_plain_staff_cannot_mutate_users(self):
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get(reverse('admin:auth_user_change', args=[self.user.pk])).status_code, 403)

    def test_delegated_staff_cannot_grant_superuser(self):
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='auth', codename='change_user'))
        response = self.client.post(reverse('admin:auth_user_change', args=[self.user.pk]), {
            'username': self.user.username, 'is_active': 'on', 'is_staff': 'on', 'is_superuser': 'on',
            'date_joined_0': timezone.localdate().isoformat(), 'date_joined_1': '12:00:00',
        })
        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.user.is_superuser)

    def test_private_download_requires_explicit_read_permission(self):
        content = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(content)
        payload = content.getvalue()
        with tempfile.TemporaryDirectory() as storage:
            with override_settings(MEDIA_ROOT=storage):
                upload = SimpleUploadedFile('privado.pdf', payload, content_type='application/pdf')
                metadata = validate_pdf(upload)
                document = Document.objects.create(case=self.case, title='Documento privado', file=upload,
                    uploaded_by=self.user, **metadata)
                url = reverse('document_download', args=[document.pk])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(b''.join(response.streaming_content), payload)
                self.client.logout()
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                outsider = User.objects.create_user('no_read_permission', password='Test-only-secret-2026')
                self.client.force_login(outsider)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.get('/media/' + document.file.name).status_code, 404)
                self.assertEqual(self.client.get('/' + document.file.name).status_code, 404)

    def test_nonstaff_admin_request_has_no_redirect_loop(self):
        response = self.client.get('/admin/', follow=True)
        self.assertEqual(response.status_code, 403)
