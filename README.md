# Casa Funeraria Baranoa

Aplicación web privada para gestionar una sola funeraria y varios usuarios. Cada servicio se organiza en un expediente con persona fallecida, solicitante, responsable del pago, autorización, servicios, documentos, trámites y movimientos financieros. La información se guarda en una base relacional; los PDF y el logo se conservan en almacenamiento privado persistente.

Interfaz en español de Colombia, importes COP y fechas en `America/Bogota`. La razón social, el NIT, la dirección, las cuentas y el logo se configuran dentro de la aplicación. No se incluyen datos legales o bancarios ficticios.

## Ejecutar en desarrollo

Requiere Python 3.12 y un navegador actual. Desde la raíz del repositorio:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DJANGO_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py bootstrap
.venv/bin/python manage.py createsuperuser
bash scripts/run-local.sh
```

El servidor escucha en el equipo local, puerto `8000`. Inicie sesión con el usuario que acaba de crear. No existen contraseñas predeterminadas. `run-local.sh` aplica migraciones e inicializa configuración y roles de forma repetible; no crea usuarios ni borra expedientes.

Los datos se guardan en `var/cfb.sqlite3` y `var/private/`. Puede seleccionar un volumen persistente con `CFB_DATA_DIR=/ruta/absoluta`. La clave de desarrollo se genera una vez en `var/.development-key`; la configuración y los datos privados quedan fuera de Git. `.env.example` es una referencia de variables: la aplicación no carga archivos `.env` automáticamente.

Cada tarea de Codex ya tiene su entorno aislado: utilice el checkout existente; no cree worktrees salvo solicitud explícita. Los procesos no sobreviven necesariamente a una nueva sesión: vuelva a ejecutar el servidor. No hace falta reinstalar si el entorno virtual y las dependencias siguen disponibles.

## Evaluación con datos ficticios

Para una demostración aislada, use una base nueva sin usuarios ni expedientes. El comando crea tres expedientes de ejemplo, PDF ficticios, facturas, abonos y costos; no configura información legal o bancaria. La contraseña se solicita sin mostrarla en pantalla:

```bash
export DJANGO_DEBUG=1
export CFB_DATA_DIR="$PWD/var/demostracion"
.venv/bin/python manage.py migrate
read -r -s -p "Contraseña de demo (mínimo 12 caracteres): " CFB_DEMO_PASSWORD
export CFB_DEMO_PASSWORD
.venv/bin/python manage.py seed_demo --username demo
unset CFB_DEMO_PASSWORD
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

`seed_demo` rechaza ejecución en producción o en una base con usuarios/expedientes. Use otra terminal sin `CFB_DATA_DIR` para volver a la base local habitual.

## Flujo principal

1. Configure los datos de empresa y cree usuarios con sus grupos de acceso.
2. Abra un expediente particular o asociado a una empresa exequial. Registre solicitante, responsable del pago y autorización disponible.
3. Agregue los servicios contratados y marque su prestación. Registre trámites, radicados y fechas.
4. Complete la lista documental cargando PDF. Cada archivo conserva autor, fecha, nombre original y huella SHA-256. La descarga comprueba permisos.
5. Registre facturas administrativas, abonos y costos. El expediente calcula facturado, recaudado, saldo, costos y margen.
6. Complete documentos, trámites y servicios para cerrar la atención. Los abonos pendientes pueden seguir recaudándose después del cierre.

Las facturas son registros administrativos internos. **Esta aplicación no emite facturas electrónicas validadas por DIAN** ni se conecta automáticamente con empresas exequiales, registradurías, notarías o bancos. El usuario registra los resultados de esos procesos.

## Acceso y control

- **Administración:** gestión completa y configuración. La administración técnica de usuarios utiliza cuentas autorizadas para el sitio administrativo de Django.
- **Operación:** expedientes, servicios, trámites y documentos.
- **Contabilidad:** facturas administrativas, abonos, costos y anulaciones.
- **Consulta:** lectura de expedientes y documentos.

Los perfiles son por función para una sola empresa; no hay separación por sede ni cartera asignada a cada usuario. La información financiera forma parte del expediente visible para los usuarios con permiso de consulta. Los cambios operativos y financieros quedan en la bitácora. El acceso directo a la base de datos sigue siendo una capacidad del administrador del servidor, por lo que la bitácora no es un registro inviolable frente a ese administrador.

Los movimientos financieros no se eliminan ni se sobrescriben en la interfaz: se anulan con motivo, conservando el historial. Se rechazan importes no positivos, fechas inconsistentes y pagos superiores al saldo. El envío repetido del mismo formulario de abono no duplica el pago.

## Verificación

```bash
export DJANGO_DEBUG=1
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py test
```

Las pruebas usan una base de datos separada; no borre la base operativa para ejecutarlas. Las pruebas de aplicación, de permisos y de reglas del negocio deben completarse antes de actualizar una instalación real.

## Prueba opcional con navegador

La prueba de navegador usa Playwright como dependencia de pruebas, independiente de los requisitos de ejecución:

```bash
.venv/bin/python -m pip install playwright==1.62.0
BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python scripts/browser_smoke.py
```

Si Chromium no está instalado en el sistema, instale el navegador administrado con `.venv/bin/python -m playwright install chromium` y ejecute el script sin `BROWSER_EXECUTABLE`. El script prepara su propia base temporal, datos ficticios y un servidor en un puerto libre; no utiliza la instalación operativa. Genera una contraseña aleatoria sin mostrarla y conserva capturas en `var/browser-smoke/`, ignorado por Git.

## Operación persistente

Consulte [arquitectura y decisiones](docs/architecture.md) y [despliegue, copias y restauración](docs/deployment.md). La instalación local usa SQLite. Para operación concurrente con varios usuarios se recomienda PostgreSQL, configurado mediante variables de entorno. El servidor de desarrollo no reemplaza Gunicorn y un proxy HTTPS en producción.

Las copias SQLite incluyen la base y los archivos privados; requieren detener las escrituras para obtener un punto coherente de ambos. La restauración valida integridad y huellas y exige un directorio nuevo. Los secretos se conservan por separado en el gestor seguro de la instalación.
