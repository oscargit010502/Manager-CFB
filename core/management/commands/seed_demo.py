"""Explicitly optional fictional data for local evaluation, never used at bootstrap."""
import os
from datetime import timedelta
from io import BytesIO
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.files.base import ContentFile
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction
from django.utils import timezone
from pypdf import PdfWriter
from core.documents import validate_pdf
from core.finance import create_invoice, register_payment, create_cost
from core.models import Case, DocumentRequirement, Document, Partner, Procedure, ServiceItem, log_event

class Command(BaseCommand):
    help = 'Datos ficticios en una base vacía local. Exige DEBUG=1 y CFB_DEMO_PASSWORD.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='demo')

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('La demostración está deshabilitada fuera de desarrollo.')
        if Case.objects.exists() or get_user_model().objects.exists():
            raise CommandError('Use una base de datos vacía y separada para la demostración.')
        password = os.environ.get('CFB_DEMO_PASSWORD', '')
        if not password:
            raise CommandError('Defina CFB_DEMO_PASSWORD; no existe una contraseña predeterminada.')
        user = get_user_model()(username=options['username'], first_name='Equipo', last_name='Demostración')
        validate_password(password, user)
        call_command('bootstrap', stdout=self.stdout)
        user.set_password(password)
        user.save()
        user.groups.add(Group.objects.get(name='Administración'))
        today = timezone.localdate()
        for index, (name, partner_name) in enumerate([
            ('Persona de ejemplo Uno', 'Grupo Recordar'),
            ('Persona de ejemplo Dos', 'Los Olivos'),
            ('Persona de ejemplo Tres', None),
        ]):
            day = today - timedelta(days=7 + index)
            partner = Partner.objects.get(name=partner_name) if partner_name else None
            case = Case.objects.create(deceased_name=name, death_date=day,
                requester_name='Solicitante de ejemplo', requester_phone='Sin teléfono real',
                payer_type='company' if partner else 'private', partner=partner,
                payer_name=partner.name if partner else 'Particular de ejemplo',
                authorization_number=f'DEMO-{index+1}', authorized_by='Autorizador de ejemplo',
                authorized_on=day, service_location='Lugar de demostración',
                notes='DATOS FICTICIOS · Solo para evaluación. No corresponde a un servicio real.',
                status='in_progress', created_by=user)
            ServiceItem.objects.create(case=case, description='Servicio funerario de ejemplo',
                quantity=1, unit_price='1500000', authorized=True, performed=index == 0,
                performed_at=timezone.now() if index == 0 else None)
            for label in ['Certificado de defunción', 'Registro civil de defunción'] + (['Autorización de la empresa'] if partner else []):
                requirement = DocumentRequirement.objects.create(case=case, label=label)
                if index == 0:
                    buffer = BytesIO()
                    writer = PdfWriter()
                    writer.add_blank_page(width=200, height=200)
                    writer.add_metadata({'/Title': 'Documento FICTICIO para demostración'})
                    writer.write(buffer)
                    file = ContentFile(buffer.getvalue(), name='ejemplo.pdf')
                    metadata = validate_pdf(file)
                    Document.objects.create(case=case, requirement=requirement, title=label + ' (DEMO)',
                        file=file, uploaded_by=user, **metadata)
            Procedure.objects.create(case=case, title='Registro de defunción',
                due_on=today + timedelta(days=index), status='done' if index == 0 else 'pending',
                completed_on=today if index == 0 else None)
            invoice = create_invoice(case=case, actor=user, amount='1500000', issued_on=day,
                due_on=today - timedelta(days=1) if index == 1 else today + timedelta(days=15),
                description='Servicio de demostración — sin validez fiscal')
            if index != 2:
                register_payment(invoice=invoice, actor=user, amount='800000', paid_on=today, method='transfer', reference='DEMO')
            create_cost(case=case, actor=user, amount='650000', incurred_on=day,
                description='Costo ficticio de atención', supplier='Proveedor de ejemplo')
            log_event(user, 'Datos ficticios de demostración', case)
        self.stdout.write(self.style.SUCCESS('Tres expedientes ficticios creados. Contraseña recibida mediante variable de entorno.'))
