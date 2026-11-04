#!/usr/bin/env python3
"""End-to-end check in a temporary database. Requires Playwright and Chromium.
Run with a Python that has playwright installed; project dependencies live in .venv.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
BROWSER = os.environ.get('BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome')


def main():
    with tempfile.TemporaryDirectory(prefix='cfb-browser-') as directory:
        data = Path(directory)
        password = secrets.token_urlsafe(28)
        today = datetime.now(ZoneInfo('America/Bogota')).date().isoformat()
        env = os.environ.copy()
        for key in list(env):
            if key.startswith('POSTGRES_') or key in ('DJANGO_SECRET_KEY', 'CFB_TRUST_PROXY'):
                env.pop(key)
        env.update(DJANGO_DEBUG='1', CFB_DATA_DIR=str(data), CFB_DEMO_PASSWORD=password)
        env.update(DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1', DJANGO_CSRF_TRUSTED_ORIGINS='')
        for args in [('migrate', '--noinput'), ('seed_demo',)]:
            subprocess.run([str(PYTHON), 'manage.py', *args], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
        fixture = next((data / 'private').rglob('*.pdf')).read_bytes()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with (data / 'server.log').open('w+') as log:
            server = subprocess.Popen([str(PYTHON), 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(100):
                    try:
                        opener.open(base + '/ingresar/', timeout=1).close()
                        break
                    except OSError:
                        if server.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        time.sleep(.1)
                else:
                    raise RuntimeError('El servidor no inició.')
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=BROWSER, headless=True, args=['--no-sandbox'])
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/ingresar/')
                    page.locator('#id_username').fill('demo')
                    page.locator('#id_password').fill(password)
                    page.get_by_role('button', name='Ingresar al sistema').click()
                    expect(page).to_have_url(base + '/')
                    expect(page.get_by_text('Persona de ejemplo Uno', exact=True)).to_be_visible()
                    screenshots = ROOT / 'var/browser-smoke'
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshots / 'dashboard-desktop.png'), full_page=True)
                    page.goto(base + '/expedientes/nuevo/')
                    for field, value in {'deceased_name':'Persona prueba navegador','death_date':today,
                        'requester_name':'Solicitante prueba','payer_name':'Particular prueba'}.items():
                        page.locator('#id_' + field).fill(value)
                    page.locator('#id_payer_type').select_option('private')
                    page.get_by_role('button', name='Guardar expediente').click()
                    expect(page.get_by_role('heading', name='Persona prueba navegador', exact=True)).to_be_visible()
                    case_url = page.url
                    page.get_by_role('link', name='Agregar servicio', exact=True).click()
                    page.locator('#id_description').fill('Traslado de prueba')
                    page.locator('#id_quantity').fill('1')
                    page.locator('#id_unit_price').fill('1500000')
                    page.locator('#id_authorized').check()
                    page.get_by_role('button', name='Guardar', exact=True).click()
                    page.get_by_role('button', name='Marcar prestado', exact=True).click()
                    for label in ['Certificado de defunción', 'Registro civil de defunción']:
                        page.get_by_role('link', name='Cargar PDF', exact=True).click()
                        page.locator('#id_title').fill(label)
                        page.locator('#id_requirement').select_option(label=label)
                        page.locator('#id_file').set_input_files({'name':'prueba.pdf','mimeType':'application/pdf','buffer':fixture})
                        page.get_by_role('button', name='Guardar', exact=True).click()
                        expect(page.get_by_text('PDF guardado en el almacenamiento privado.',exact=True)).to_be_visible()
                    with page.expect_download() as download:
                        page.get_by_role('link', name='Descargar PDF',exact=True).first.click()
                    assert Path(download.value.path()).read_bytes() == fixture
                    page.locator('#tramites').get_by_role('link', name='Actualizar',exact=True).click()
                    page.locator('#id_status').select_option('done')
                    page.get_by_role('button', name='Guardar',exact=True).click()
                    page.get_by_role('link', name='Registrar factura',exact=True).click()
                    for field, value in {'amount':'1500000','description':'Atención prueba navegador',
                        'issued_on':today,'due_on':today}.items():
                        page.locator('#id_'+field).fill(value)
                    page.get_by_role('button', name='Registrar factura',exact=True).click()
                    page.get_by_role('link', name='Registrar costo',exact=True).click()
                    for field, value in {'amount':'650000','description':'Traslado proveedor prueba','incurred_on':today}.items():
                        page.locator('#id_'+field).fill(value)
                    page.get_by_role('button', name='Registrar costo',exact=True).click()
                    page.get_by_role('button', name='Cerrar atención',exact=True).click()
                    expect(page.get_by_text('Expediente cerrado.', exact=True)).to_be_visible()
                    page.get_by_role('link', name='Registrar abono',exact=True).click()
                    page.locator('#id_amount').fill('800000')
                    page.locator('#id_paid_on').fill(today)
                    page.locator('#id_method').select_option('transfer')
                    page.get_by_role('button', name='Registrar abono',exact=True).click()
                    expect(page).to_have_url(case_url)
                    expect(page.locator('.summary-grid')).to_contain_text('700.000,00')
                    expect(page.locator('.summary-grid')).to_contain_text('850.000,00')
                    page.screenshot(path=str(screenshots / 'case-desktop.png'), full_page=True)
                    for width in (768, 1024):
                        page.set_viewport_size({'width':width,'height':1024})
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Desbordamiento en tableta {width}'
                    page.screenshot(path=str(screenshots / 'case-tablet.png'), full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    page.goto(base + '/')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Desbordamiento horizontal en móvil'
                    page.get_by_role('button',name='Abrir menú').click()
                    expect(page.get_by_role('link',name='Expedientes',exact=True)).to_be_visible()
                    page.get_by_role('link',name='Expedientes',exact=True).click()
                    page.goto(case_url)
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Desbordamiento en detalle móvil'
                    page.screenshot(path=str(screenshots / 'case-mobile.png'), full_page=True)
                    page.get_by_role('button',name='Cerrar sesión').click()
                    expect(page).to_have_url(base + '/ingresar/')
                    page.goto(case_url)
                    expect(page).to_have_url(base + '/ingresar/?next=' + case_url.removeprefix(base))
                    assert not errors, errors
                    browser.close()
                print('OK: ingreso, expediente, servicio, 2 PDF, descarga, trámite, factura, costo, cierre, abono posterior, saldos, móvil y salida. Capturas: var/browser-smoke/.')
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()

if __name__ == '__main__':
    main()
