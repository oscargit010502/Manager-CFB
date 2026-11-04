# Instalación y operación

## Desarrollo

Siga el README. Utilice el checkout existente y Python 3.12. No se requieren cuentas externas para probar el núcleo con SQLite. Si un entorno ya contiene `.venv` y los datos, reutilícelos. Los procesos se reinician con `bash scripts/run-local.sh`; no se debe suponer que un proceso sigue vivo tras restaurar un entorno.

`DJANGO_DEBUG=1` es exclusivamente para desarrollo local. Las cuentas se crean con `createsuperuser` o mediante la administración autorizada. No hay una contraseña compartida de instalación. Asigne los grupos creados por `bootstrap` y use usuarios personales para conservar trazabilidad.

## Producción con PostgreSQL y HTTPS

Prepare Python 3.12, un usuario del sistema dedicado, PostgreSQL, un volumen de datos privado y un proxy inverso con certificado HTTPS válido. Estas instrucciones preparan una instalación; no constituyen una publicación ni certifican una infraestructura externa.

Configure las variables en el gestor de servicios o secretos:

| Variable | Uso |
| --- | --- |
| `DJANGO_DEBUG` | `0` en producción. |
| `DJANGO_SECRET_KEY` | Clave aleatoria privada y estable; nunca guardarla en Git ni en una orden compartida. |
| `DJANGO_ALLOWED_HOSTS` | Nombres DNS reales separados por comas. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes HTTPS reales separados por comas. |
| `CFB_DATA_DIR` | Ruta absoluta del volumen persistente privado. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Base, usuario de mínimo privilegio y contraseña de PostgreSQL. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Ubicación de PostgreSQL. |
| `POSTGRES_SSLMODE` | Para un servidor remoto, `verify-full` con CA confiable y nombre de servidor correcto. |
| `CFB_TRUST_PROXY` | `1` únicamente cuando el proxy confiable reemplaza `X-Forwarded-Proto` y bloquea acceso directo al proceso. |

`.env.example` documenta nombres, no activa configuración. No reutilice la clave local de desarrollo en producción. Los datos bancarios y legales se introducen desde la configuración de la aplicación.

Desde la raíz del proyecto, con esas variables presentes:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py bootstrap
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
.venv/bin/gunicorn cfb.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 60
```

Ejecute Gunicorn como servicio con reinicio y logs protegidos. Dos workers son un punto inicial para PostgreSQL; ajuste según recursos y mediciones. Si usa SQLite temporalmente, limite la concurrencia y use un worker; el motor puede serializar escrituras, pero no sustituye PostgreSQL para uso intenso.

El proxy debe pasar `Host`, reemplazar `X-Forwarded-Proto`, limitar las cargas a 12 MiB, aplicar tiempos de espera y restringir el acceso al sistema privado según la red elegida. No exponga directamente Gunicorn. WhiteNoise sirve únicamente archivos estáticos de `staticfiles/`. **No cree un alias público para `CFB_DATA_DIR` o `private/`.**

La lista de hosts de producción y los certificados dependen del despliegue elegido. No se necesita inventarlos ni publicar el entorno para desarrollar o probar el código. La configuración con PostgreSQL debe probarse contra el servidor real antes de adoptar la instalación.

## Copia coherente de SQLite y documentos

La base y los archivos deben corresponder al mismo punto en el tiempo. Detenga Gunicorn o el servidor de desarrollo antes de realizar la copia y manténgalo detenido durante la operación. El script exige confirmación explícita de ese estado; no detiene servicios por sí mismo.

```bash
python3 scripts/backup.py --data-dir /ruta/datos/cfb \
  --output /ruta/copias/cfb-2026-11-04.zip --maintenance-confirmed
```

El script usa la API de copia de SQLite, verifica `PRAGMA integrity_check`, comprueba que existan los archivos referenciados por la base y añade todos los archivos privados a un ZIP con manifiesto SHA-256. El archivo final se publica de forma atómica sin sobrescribir una copia existente. Los enlaces simbólicos se rechazan. La clave de desarrollo, las variables y los secretos no se incluyen.

Guarde las copias cifradas en un destino separado del servidor y compruebe periódicamente su restauración. El ZIP no cifra el contenido; sus huellas detectan corrupción accidental, no demuestran autenticidad frente a quien pueda alterar simultáneamente datos y manifiesto. La retención y el cifrado del destino se configuran con la infraestructura de la empresa.

## Restauración

Restaure primero en un directorio **nuevo**:

```bash
python3 scripts/restore.py /ruta/copias/cfb-2026-11-04.zip \
  --data-dir /ruta/datos/cfb-restaurado
```

El comando valida nombres y rutas, ausencia de entradas duplicadas o enlaces, tamaños y huellas, integridad SQLite y archivos referenciados. No sobreescribe directorios existentes. El límite predeterminado del contenido descomprimido es 10 GiB; `--max-bytes` permite ajustarlo para una copia confiable mayor.

Con la aplicación aún detenida, apunte `CFB_DATA_DIR` al nuevo directorio, restablezca la clave de producción desde el gestor de secretos y ejecute `manage.py check`. Conserve la instalación anterior hasta comprobar inicio de sesión, consulta del expediente, saldo y descarga de un archivo. Después habilite acceso y reinicie el servicio. No es necesario importar contraseñas manualmente: las cuentas y sus hashes están en la base restaurada.

Las verificaciones realizadas sobre los scripts incluyeron restauración real de datos SQLite y un archivo, rechazo de sobrescritura, rechazo de checksum incorrecto, intento de traversal, límite de tamaño y archivo referenciado ausente.

## Copias con PostgreSQL

Los scripts anteriores son para SQLite. Con PostgreSQL, detenga las escrituras, haga una copia con `pg_dump` y copie el directorio privado durante la misma ventana. Gestione autenticación con los mecanismos seguros de PostgreSQL, sin incluir contraseñas en órdenes o nombres de archivos. Verifique una restauración con `pg_restore` en una base nueva y compruebe las descargas antes de reemplazar el servicio. Guarde también la versión de aplicación y el estado de migraciones junto con la copia.

## Actualizaciones

Realice una copia validada antes de cambiar la versión. Instale las dependencias fijadas, ejecute pruebas, revise las nuevas migraciones, aplíquelas y regenere estáticos. Reinicie los procesos para cargar el código. No ejecute `flush`, elimine `var/` ni cargue datos de demostración sobre una instalación operativa. Las migraciones no deben ejecutarse simultáneamente desde varios workers.
