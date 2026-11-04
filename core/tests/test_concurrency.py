"""Exercise competing payment commands against the configured file-backed SQLite.

Django's normal test database is in memory. Separate subprocesses deliberately
load the real SQLite settings and migrations in temporary, isolated data folders.
This suite does not claim to validate PostgreSQL locking.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONCURRENT_PAYMENTS = r'''
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.utils import timezone
from core.finance import create_invoice, register_payment
from core.models import AuditEvent, Case, Invoice, Payment

scenario = sys.argv[1]
db = settings.DATABASES['default']
assert db['ENGINE'] == 'django.db.backends.sqlite3'
assert str(db['NAME']) != ':memory:' and not str(db['NAME']).startswith('file:memory')
assert db['OPTIONS']['transaction_mode'] == 'IMMEDIATE'
assert db['OPTIONS']['timeout'] == 20

actor = get_user_model().objects.create_superuser(
    username='concurrency-test', password=None, email='')
today = timezone.localdate()
case = Case.objects.create(deceased_name='Persona ficticia de concurrencia',
    death_date=today, requester_name='Solicitante ficticio', payer_type='private',
    payer_name='Pagador ficticio', created_by=actor)
invoice = create_invoice(case=case, actor=actor, amount='100.00', issued_on=today,
    due_on=today, description='Factura ficticia de concurrencia')
actor_id, invoice_id = actor.pk, invoice.pk
keys = [uuid4(), uuid4()]
if scenario == 'duplicate':
    keys[1] = keys[0]
barrier = Barrier(2)


def submit(key):
    close_old_connections()
    try:
        # No shared ORM instances or connections between request simulations.
        local_actor = get_user_model().objects.get(pk=actor_id)
        local_invoice = Invoice.objects.get(pk=invoice_id)
        connection_id = id(connections['default'].connection)
        barrier.wait(timeout=10)
        try:
            payment = register_payment(invoice=local_invoice, actor=local_actor,
                amount='80.00', paid_on=today, method='cash', reference='PRUEBA',
                notes='', idempotency_key=key)
        except ValidationError as error:
            return {'outcome': 'rejected', 'messages': error.messages,
                    'connection_id': connection_id}
        return {'outcome': 'accepted', 'payment_id': payment.pk,
                'connection_id': connection_id}
    finally:
        connections.close_all()


with ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(submit, key) for key in keys]
    results = [future.result(timeout=30) for future in futures]

invoice.refresh_from_db()
print(json.dumps({'results': results, 'balance': str(invoice.balance),
    'paid_total': str(invoice.paid_total),
    'payment_count': Payment.objects.filter(invoice=invoice).count(),
    'payment_audit_count': AuditEvent.objects.filter(case=case,
        action='Abono registrado').count()}))
connections.close_all()
'''


class SQLitePaymentConcurrencyTests(SimpleTestCase):
    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory(prefix='cfb-concurrency-') as data_dir:
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith('POSTGRES_')}
            environment.update({'DJANGO_SETTINGS_MODULE': 'cfb.settings',
                                'DJANGO_DEBUG': '1', 'CFB_DATA_DIR': data_dir})
            migration = subprocess.run(
                [sys.executable, 'manage.py', 'migrate', '--noinput', '--verbosity', '0'],
                cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(migration.returncode, 0, migration.stdout + migration.stderr)
            execution = subprocess.run(
                [sys.executable, '-c', CONCURRENT_PAYMENTS, scenario],
                cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
            result = json.loads(execution.stdout)
        self.assertEqual(len({entry['connection_id'] for entry in result['results']}), 2,
                         'The two workers must use separate database connections.')
        self.assertEqual(result['balance'], '20.00')
        self.assertEqual(result['paid_total'], '80.00')
        self.assertEqual(result['payment_count'], 1)
        self.assertEqual(result['payment_audit_count'], 1)
        return result

    def test_competing_payments_cannot_overdraw_the_invoice(self):
        result = self.run_scenario('competing')
        self.assertCountEqual([entry['outcome'] for entry in result['results']],
                              ['accepted', 'rejected'])
        rejection = next(entry for entry in result['results'] if entry['outcome'] == 'rejected')
        self.assertIn('El abono supera el saldo pendiente de la factura.', rejection['messages'])

    def test_simultaneous_retries_record_one_payment_and_one_audit(self):
        result = self.run_scenario('duplicate')
        self.assertEqual([entry['outcome'] for entry in result['results']],
                         ['accepted', 'accepted'])
        self.assertEqual(result['results'][0]['payment_id'], result['results'][1]['payment_id'])
