# Evidencia de validación

Validación local realizada el 4 de noviembre de 2026, con Python 3.12.14 y Django 5.2.19.

## Etapas verificadas

1. **Base ejecutable:** instalación de dependencias fijadas, migración inicial, inicialización repetible de empresa/catálogos/roles y verificación de dependencias sin incompatibilidades.
2. **Operación:** expedientes particulares y empresariales, autorizaciones, servicios prestados, documentos privados, trámites y cierre/reapertura con validaciones.
3. **Finanzas:** cálculos decimales, facturas administrativas, abonos, costos, anulaciones e historial. Dos solicitudes concurrentes no duplican el mismo abono ni permiten recaudar por encima del saldo en SQLite.
4. **Persistencia y seguridad:** sesiones, permisos, CSRF, restricción de intentos de acceso, rechazo de PDF inválidos/activos, aislamiento de documentos y respaldo/restauración con verificación de integridad.
5. **Interfaz y servidor:** flujo real de navegador, vistas adaptables, inicio con Gunicorn y CSS servido por WhiteNoise.

## Resultados

- `manage.py test`: **68 pruebas aprobadas**. Incluye 9 pruebas de copia/restauración y 2 pruebas concurrentes con SQLite en archivo y conexiones separadas.
- `manage.py makemigrations --check --dry-run`: ninguna migración pendiente.
- `manage.py check`: sin incidencias.
- `manage.py check --deploy --fail-level WARNING`, usando configuración de producción y una clave temporal: sin advertencias.
- `pip check`: sin dependencias incompatibles.
- `scripts/browser_smoke.py`: ingreso, creación de expediente, servicio autorizado/prestado, dos cargas PDF, descarga con bytes idénticos, trámite finalizado, factura, costo, cierre, abono posterior, saldo y margen correctos, navegación móvil y cierre de sesión. Base temporal separada, sin credenciales predeterminadas.
- Gunicorn con `DEBUG=0` y simulación local de un proxy HTTPS confiable: página de ingreso y CSS compilado respondieron HTTP 200; cabeceras privadas presentes.

Las capturas de la prueba se generan en `var/browser-smoke/`, fuera de Git. La prueba de navegador requiere Playwright y Chromium; la aplicación no los necesita para funcionar.

## Alcance de la evidencia

Se validó SQLite. La conexión PostgreSQL está implementada, pero no se ejecutaron pruebas contra una instancia PostgreSQL real. La prueba local de Gunicorn no constituye un despliegue público ni valida un certificado TLS real. No se publicó el entorno ni se enviaron cambios al repositorio remoto.

Los documentos de prueba son ficticios. No se verificaron integraciones con DIAN, bancos, registradurías ni empresas exequiales porque no forman parte de la integración implementada. Los trámites y facturas se registran administrativamente en la aplicación.
