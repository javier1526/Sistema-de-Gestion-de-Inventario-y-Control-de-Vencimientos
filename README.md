# Sistema de Gestión de Inventario y Control de Vencimientos

## Descripción

Aplicación web para gestionar productos, lotes y movimientos de mercadería en
la bodega de un supermercado, con control de existencias y fechas de vencimiento.
El control del sistema termina con el retiro de mercadería de la bodega.

El prototipo está destinado a ejecución local. Su interfaz mobile-first se
adapta a teléfonos y computadores y utiliza Bootstrap desde archivos locales.

## Funcionalidades principales

- Gestión de productos: registro, edición de nombre y stock mínimo y eliminación
  con confirmación únicamente cuando no existen antecedentes de inventario.
- Registro de ingresos por lotes nuevos, con cantidad y costo unitario de
  adquisición en pesos chilenos.
- Control de vencimientos: un lote que vence hoy sigue vigente durante ese día;
  se considera vencido desde el día siguiente.
- Consulta de stock físico, que incluye unidades vencidas, y stock disponible,
  que las excluye.
- Ordenamiento FEFO como recomendación de rotación.
- Retiros de mercadería del lote elegido, con validación del saldo actualizado.
- Rechazo de retiros de lotes vencidos, agotados o con unidades insuficientes.
- Alertas internas dinámicas cuando el disponible es menor o igual al mínimo.
- Historial de ingresos y retiros con fecha, responsable, producto, lote y cantidad.
- Análisis del valor potencial en riesgo por vencimiento en intervalos
  independientes de 0–30, 31–60 y 61–90 días, según saldo y costo de cada lote.

Los ingresos y retiros se guardan junto con sus movimientos en transacciones.
El análisis económico no registra pérdidas contables ni da de baja mercadería.

## Perfiles de usuario

| Perfil | Operaciones |
|---|---|
| Administrador | Gestionar productos, registrar ingresos y consultar alertas, historial y análisis económico. |
| Reponedor | Consultar productos y existencias y registrar retiros. |
| Ambos | Consultar inventario, lotes vigentes, vencidos y agotados. |

**FEFO es una recomendación:** el Reponedor puede retirar de cualquier lote
vigente con unidades; no está obligado a escoger el primero.

Cada trabajador utiliza una cuenta individual activa y exactamente uno de los
grupos operativos Administrador o Reponedor. Los permisos se verifican en el
servidor, también al acceder directamente por URL.

## Tecnologías

| Tecnología | Versión de referencia |
|---|---|
| Python | 3.14.7 |
| Django | 6.1.1 |
| MySQL Community Server | 8.4.13, con InnoDB |
| mysqlclient | 2.3.0 |
| python-dotenv | 1.2.4 |
| Bootstrap | 5.3.8, incluido localmente |
| Interfaz | HTML, CSS y plantillas Django |

Las dependencias Python están fijadas en requirements.txt. El idioma es español
de Chile y la zona horaria es America/Santiago.

El código se organiza en usuarios (autenticación y permisos), inventario
(productos, lotes, ingresos, consultas y retiros) y consultas (lecturas
administrativas). sistema_inventario_bodega contiene la configuración Django.

## Requisitos previos

- Git, Python 3.14 y MySQL 8.4.13 instalados en el computador.
- MySQL iniciado en 127.0.0.1:3306 para utilizar el asistente de preparación incluido.
- Acceso administrativo a MySQL para crear una base y una cuenta de aplicación.
- PowerShell en Windows para los comandos siguientes y un navegador actualizado.

El conector mysqlclient requiere un paquete compatible con el intérprete y la
plataforma; si pip necesita compilarlo, serán necesarias las herramientas de
compilación correspondientes. No se utiliza XAMPP.

## Instalación y configuración

### 1. Clonar el repositorio

Sustituye URL_DEL_REPOSITORIO por la dirección real del repositorio:

~~~powershell
git clone "https://github.com/javier1526/Sistema-de-Gestion-de-Inventario-y-Control-de-Vencimientos.git" sistema_inventario_bodega
Set-Location sistema_inventario_bodega
~~~

### 2. Crear y activar el entorno virtual

Usa el ejecutable de Python 3.14 de tu instalación:

~~~powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
~~~

Si la activación no está disponible en tu terminal, los pasos siguientes usan
directamente el ejecutable del entorno y no dependen de activarlo.

### 3. Instalar las dependencias

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
~~~

### 4. Preparar la configuración local

.env.example es una plantilla pública sin contraseñas. El siguiente comando
crea .env con una clave Django aleatoria sin mostrarla y se niega a sobrescribir
un archivo existente. Ejecútalo solo si todavía no tienes .env:

~~~powershell
@'
from pathlib import Path
from secrets import token_urlsafe

plantilla = Path('.env.example').read_text(encoding='utf-8')
contenido = plantilla.replace(
    'DJANGO_SECRET_KEY=\n', f'DJANGO_SECRET_KEY={token_urlsafe(48)}\n', 1
)
with Path('.env').open('x', encoding='utf-8') as archivo:
    archivo.write(contenido)
'@ | .\.venv\Scripts\python.exe -B -
~~~

Completa únicamente la copia local:

| Variable | Uso |
|---|---|
| DJANGO_SECRET_KEY | Clave aleatoria estable generada para esta instalación. |
| DJANGO_DEBUG | True solo para desarrollo local; no representa una configuración de producción. |
| DJANGO_ALLOWED_HOSTS | localhost,127.0.0.1,[::1] para acceso local. |
| MYSQL_DATABASE | inventario_bodega |
| MYSQL_USER | bodega_app; la configuración rechaza otro usuario. |
| MYSQL_PASSWORD | Contraseña de la cuenta de aplicación, obtenida en el paso siguiente. |
| MYSQL_HOST | 127.0.0.1 |
| MYSQL_PORT | 3306 |

Django carga .env automáticamente. Las variables ya definidas en la terminal
prevalecen sobre el archivo; evita cargar configuraciones antiguas en esa sesión.
Conserva la clave Django entre ejecuciones. .env está excluido de Git:
no lo publiques, no compartas sus valores y comparte solo .env.example.

### 5. Crear la base MySQL y la cuenta de aplicación

Para una instalación nueva, el asistente incluido comprueba versión, puerto,
motor y existencia previa de objetos:

~~~powershell
.\.venv\Scripts\python.exe -B scripts\preparar_mysql.py inspeccionar
~~~

Si confirma MySQL 8.4.13, puerto 3306, InnoDB y ausencia de la base y cuenta,
puedes preparar ambos:

~~~powershell
.\.venv\Scripts\python.exe -B scripts\preparar_mysql.py crear
~~~

El procedimiento crea inventario_bodega con utf8mb4 y bodega_app@127.0.0.1.
MySQL genera una contraseña aleatoria de 32 caracteres. El script solicita
root mediante entrada oculta y muestra una línea MYSQL_PASSWORD para copiar
directamente a .env, conservando comillas y escapes. Utiliza una terminal
local sin transcripción, grabación o redirección de salida.

La cuenta de aplicación recibe SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER,
INDEX y REFERENCES únicamente sobre ese esquema. No se conceden permisos
administrativos globales ni GRANT OPTION. Django se conecta con bodega_app,
nunca con root.

Si la base o cualquier cuenta bodega_app ya existe, el asistente se detiene:
no la elimines ni repitas la creación. Utiliza la configuración existente
solo después de comprobar que corresponde a esta instalación y conserva sus datos.

### 6. Comprobar la conexión y aplicar migraciones

Con .env completo y MySQL iniciado:

~~~powershell
.\.venv\Scripts\python.exe -B manage.py verificar_base --base-esperada inventario_bodega
.\.venv\Scripts\python.exe -B manage.py check --database default
.\.venv\Scripts\python.exe -B manage.py migrate --plan --database default
~~~

Revisa el destino y el plan antes de aplicar las migraciones:

~~~powershell
.\.venv\Scripts\python.exe -B manage.py migrate --database default
~~~

Las migraciones incluidas construyen las tablas estándar de Django y los
modelos Producto, Lote y Movimiento. No es necesario importar datos privados,
respaldos o cuentas de otra instalación.

### 7. Configurar perfiles y cuentas individuales

~~~powershell
.\.venv\Scripts\python.exe -B manage.py preparar_perfiles
.\.venv\Scripts\python.exe -B manage.py configurar_usuario --usuario admin_bodega --perfil Administrador
.\.venv\Scripts\python.exe -B manage.py configurar_usuario --usuario reponedor_bodega --perfil Reponedor
~~~

Los nombres son ejemplos: elige uno distinto para cada trabajador. Las
contraseñas se solicitan de forma oculta y se validan mediante Django.
configurar_usuario no sobrescribe cuentas existentes y no concede permisos
de personal o superusuario.

Para mantener trabajadores desde el panel técnico, crea una cuenta técnica
separada mediante el comando interactivo:

~~~powershell
.\.venv\Scripts\python.exe -B manage.py createsuperuser
~~~

Esa cuenta permite administrar usuarios y grupos en /admin/. No le asignes
un grupo operativo si solo realizará mantenimiento técnico. Ser superusuario
no otorga automáticamente acceso a las operaciones de bodega.

Desde el panel, crea cada trabajador con contraseña utilizable y cuenta activa,
asígnale exactamente un grupo operativo y conserva desmarcados los permisos
de personal y superusuario. Producto, Lote y Movimiento no están registrados
en el panel: se gestionan mediante las funciones de la aplicación.

### 8. Iniciar el servidor y acceder

~~~powershell
.\.venv\Scripts\python.exe -B manage.py runserver 127.0.0.1:8000
~~~

Abre http://127.0.0.1:8000/ e inicia sesión con una cuenta operativa configurada.
El panel técnico está en http://127.0.0.1:8000/admin/. Para detener el servidor,
utiliza Ctrl+C.

El servidor de desarrollo y DJANGO_DEBUG=True son para uso local, no un
despliegue público. El diseño es responsivo. Una prueba desde otro dispositivo
de la misma red requiere configurar explícitamente la IP local permitida y
el acceso al servidor; no se habilita la red automáticamente.

## Ejecución de pruebas

Desde la raíz del proyecto:

~~~powershell
.\.venv\Scripts\python.exe -B manage.py check --settings=sistema_inventario_bodega.settings_pruebas
.\.venv\Scripts\python.exe -B manage.py test usuarios inventario consultas --settings=sistema_inventario_bodega.settings_pruebas --verbosity=2
~~~

La suite contiene 98 métodos y utiliza exclusivamente SQLite en memoria.
settings_pruebas desactiva la carga de .env y sustituye el backend MySQL.
Django prepara y destruye el esquema temporal durante la ejecución.

Incluye validaciones, perfiles, CSRF, sesiones, operaciones de inventario,
rollback, consultas y administración técnica de cuentas. Los valores de
contraseña de las fixtures son ficticios y no provisionan cuentas persistentes.

SQLite no reproduce los bloqueos de filas de InnoDB. La comprobación adicional
de concurrencia requiere MySQL real y el destino exacto previsto por el script:

~~~powershell
.\.venv\Scripts\python.exe -B -m scripts.verificar_concurrencia_retiros
~~~

Este script no se ejecuta con la suite anterior. Crea y limpia registros
aislados, por lo que solo debe utilizarse en una instalación de prueba
controlada, después de revisar su destino y efectos. No equivale a una prueba
secuencial de SQLite ni debe ejecutarse automáticamente sobre inventario real.

## Autores

**Desarrollado por:**

- Javier Vasquez
- Christian Jimenez

## Recursos de terceros

Bootstrap 5.3.8 conserva su licencia MIT y las atribuciones originales en
static/vendor/bootstrap/5.3.8/LICENSE y en los archivos distribuidos.
