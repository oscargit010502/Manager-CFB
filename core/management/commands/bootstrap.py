from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Company, Partner

class Command(BaseCommand):
    help = 'Crea configuración vacía, empresas y roles sin contraseñas ni datos legales inventados.'

    @transaction.atomic
    def handle(self, *args, **options):
        Company.objects.get_or_create(pk=1)
        for name in ['Grupo Recordar', 'Los Olivos', 'Cooserpark']:
            Partner.objects.get_or_create(name=name)
        roles = {
            'Administración': ['view_case', 'manage_operations', 'manage_finance', 'manage_settings'],
            'Operación': ['view_case', 'manage_operations'],
            'Contabilidad': ['view_case', 'manage_finance'],
            'Consulta': ['view_case'],
        }
        for name, codenames in roles.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.add(*Permission.objects.filter(content_type__app_label='core', codename__in=codenames))
        self.stdout.write(self.style.SUCCESS('Configuración y roles preparados. Cree el administrador con createsuperuser.'))
