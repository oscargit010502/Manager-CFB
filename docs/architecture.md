# Arquitectura y decisiones

## Base tecnológica

Monolito modular de Django 5.2 LTS, Python 3.12, plantillas renderizadas en servidor y CSS/JavaScript local sin CDN. Django aporta autenticación de usuarios, permisos, sesiones, formularios, protección CSRF, ORM, migraciones y ejecutor de pruebas. Se evitan microservicios y proveedores pagos obligatorios.

La [documentación oficial de instalación de Django 5.2](https://raw.githubusercontent.com/django/django/stable/5.2.x/docs/faq/install.txt), consultada al implementar, confirma compatibilidad con Python 3.10–3.14 y soporte de SQLite y PostgreSQL. La descarga de `docs.djangoproject.com` estaba restringida en el entorno; se consultó el mismo documento en el repositorio oficial. Las versiones exactas se fijan en `requirements.txt` y se verifican mediante instalación y pruebas.

SQLite permite ejecutar el núcleo sin credenciales externas. PostgreSQL es la opción recomendada para varios usuarios escribiendo simultáneamente. El almacenamiento de archivos es el sistema de archivos privado del servidor; debe estar en un volumen persistente respaldado, no en una capa efímera de contenedor. El navegador no almacena expedientes, dinero o documentos en `localStorage`.

## Módulos y modelo

- `cfb/`: configuración, rutas y punto de entrada WSGI.
- `core/models.py`: empresa, empresas exequiales, expedientes, servicios, trámites, requisitos documentales, archivos, facturas, abonos, costos y auditoría.
- `core/views.py` y `core/forms.py`: operación y configuración.
- `core/finance.py`: transacciones financieras y reglas de consistencia; vistas y formularios financieros separados.
- `core/dashboard_views.py`: tablero, filtros y consulta.
- `templates/` y `static/`: interfaz accesible y adaptable a pantallas pequeñas.
- `core/tests/`: validación funcional, permisos, archivos y reglas de negocio.

Cada expediente tiene un código interno estable. La lista de documentos permite distinguir un requisito pendiente de un archivo recibido. Los trámites distinguen pendientes, en curso y completos. Los servicios distinguen autorización y prestación: no basta con haber contratado una actividad para considerarla realizada.

Los importes utilizan decimales, nunca valores flotantes. El saldo resulta de facturas vigentes menos abonos no anulados. El margen administrativo resulta de facturación vigente menos costos no anulados; no equivale al efectivo disponible, a utilidad fiscal ni a estados financieros contables.

Las operaciones de dinero utilizan transacciones y bloqueos de registros. PostgreSQL proporciona bloqueos por fila; SQLite usa transacciones inmediatas para serializar escrituras. Los abonos incluyen una clave de idempotencia para rechazar duplicación por reenvío de formulario. Las anulaciones exigen un motivo; la factura solo se anula cuando no tiene abonos vigentes.

## Suposiciones de negocio

1. Una empresa, varios usuarios y una única moneda: COP.
2. Usuarios autorizados pueden consultar todos los expedientes. No hay permisos por sede ni asignación individual de casos.
3. La recepción puede comenzar mientras se completa una autorización; el cierre exige los requisitos operativos indicados por la aplicación.
4. El cierre es operativo: permite seguir registrando o anulando abonos. Facturas y costos no se modifican en expedientes cerrados; un usuario con permiso de configuración puede reabrir el expediente indicando un motivo que queda en la bitácora. La cancelación no debe dejar movimientos financieros vigentes.
5. Las referencias internas de factura no representan numeración fiscal autorizada. La integración con DIAN, impuestos, notas crédito fiscales y contabilidad formal quedan fuera de este núcleo.
6. Los trámites ante entidades externas se coordinan y documentan manualmente. No se envían mensajes ni solicitudes automáticamente.
7. Se conserva el historial de archivos y movimientos. No existe borrado permanente de expedientes desde el flujo ordinario.
8. No se presupone ninguna razón social, NIT, dirección, banco o cuenta. Los nombres de empresas exequiales son un catálogo editable de referencia.

## Seguridad y límites

Autenticación obligatoria, permisos por función, mutaciones por POST con CSRF, validación de formularios, plantillas con escape y descargas privadas. Los archivos se guardan con nombres aleatorios y permisos restrictivos; se validan tipo, contenido y tamaño. Los PDF se entregan como descarga, sin una ruta pública de medios. Los archivos privados nunca deben ser publicados por Nginx, Apache, un CDN o WhiteNoise.

Las cookies y la política HTTPS se endurecen al desactivar `DJANGO_DEBUG`. La clave de producción debe venir del gestor de secretos; el proceso falla si no está configurada. La aplicación incluye cabeceras contra almacenamiento en caché de respuestas privadas y contra inclusión de contenido ejecutable externo.

La validación estructural de un PDF no equivale a un análisis antimalware. Para entornos con requisitos adicionales, incorpore un escáner de archivos antes de habilitar la descarga. No se han implementado firma digital, MFA, cifrado de documentos a nivel de aplicación ni automatización de retención legal. Proteja disco, copias y accesos administrativos, y determine los plazos de conservación según las obligaciones aplicables antes de introducir información real.
