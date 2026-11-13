"""Inspección y preparación inicial de MySQL para el desarrollo en Windows."""

import argparse
from contextlib import closing
from getpass import GetPassWarning, getpass
import sys
import warnings

import MySQLdb


DESTINO = {
    'host': '127.0.0.1',
    'port': 3306,
    'charset': 'utf8mb4',
    'connect_timeout': 5,
    'ssl_mode': 'REQUIRED',
}
BASE = 'inventario_bodega'
USUARIO = 'bodega_app'

SQL_SERVIDOR = (
    'SELECT VERSION(), @@port, @@default_storage_engine, @@partial_revokes'
)
SQL_BASE = """
SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s
"""
SQL_TABLAS = """
SELECT TABLE_NAME, TABLE_TYPE, ENGINE
FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME
"""
SQL_CUENTAS = (
    'SELECT Host, plugin FROM mysql.user WHERE User = %s ORDER BY Host'
)
SQL_CREAR_BASE = """
CREATE DATABASE inventario_bodega
CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci
"""
SQL_CREAR_CUENTA = """
CREATE USER 'bodega_app'@'127.0.0.1'
IDENTIFIED WITH caching_sha2_password BY RANDOM PASSWORD
"""
SQL_PERMISOS = """
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
ON `{base}`.* TO 'bodega_app'@'127.0.0.1'
"""
SQL_VERIFICAR = 'SELECT VERSION(), DATABASE(), CURRENT_USER()'


def inspeccionar(cursor):
    cursor.execute(SQL_SERVIDOR)
    version, puerto, motor, revocaciones_parciales = cursor.fetchone()
    print(f'MySQL {version} | Puerto {puerto} | Motor predeterminado {motor}')
    cursor.execute(SQL_BASE, (BASE,))
    base_existente = cursor.fetchone()
    if base_existente:
        codificacion, cotejamiento = base_existente
        print(f'Base existente: {BASE} ({codificacion}, {cotejamiento}).')
        cursor.execute(SQL_TABLAS, (BASE,))
        tablas = cursor.fetchall()
        print(f'Objetos de tipo tabla o vista: {len(tablas)}')
        for nombre, tipo, motor_tabla in tablas:
            print(f'  {nombre}: {tipo}, {motor_tabla or "sin motor"}')
    else:
        print(f'La base {BASE} no existe.')

    cursor.execute(SQL_CUENTAS, (USUARIO,))
    cuentas = cursor.fetchall()
    if cuentas:
        for anfitrion, autenticacion in cuentas:
            print(
                f'Cuenta existente: {USUARIO}@{anfitrion} ({autenticacion}).'
            )
    else:
        print(f'No existe ninguna cuenta llamada {USUARIO}.')

    if base_existente or cuentas:
        raise SystemExit('Revisar los objetos encontrados antes de continuar.')
    if version.split('-', 1)[0] != '8.4.13' or puerto != 3306:
        raise SystemExit(
            'El servidor no coincide con la versión y el puerto previstos.'
        )
    if motor.upper() != 'INNODB':
        raise SystemExit('El motor predeterminado debe ser InnoDB.')
    return bool(int(revocaciones_parciales))


def crear(cursor, revocaciones_parciales):
    cursor.execute(SQL_CREAR_BASE)
    print(f'Base {BASE} creada.')
    cursor.execute('SET SESSION generated_random_password_length = 32')
    cursor.execute(SQL_CREAR_CUENTA)
    _, _, clave_mysql, _ = cursor.fetchone()
    print(f'Cuenta {USUARIO}@127.0.0.1 creada.')
    # Entregar la clave aun si luego falla el GRANT o la verificación.
    clave_para_env = clave_mysql.replace('\\', '\\\\').replace("'", "\\'")
    print('Copia esta línea al archivo .env y reemplaza MYSQL_PASSWORD.')
    print(f"MYSQL_PASSWORD='{clave_para_env}'", flush=True)

    # Con partial_revokes desactivado, el guion bajo sería un comodín.
    esquema = BASE if revocaciones_parciales else r'inventario\_bodega'
    cursor.execute(SQL_PERMISOS.format(base=esquema))
    print(f'Permisos concedidos para {BASE}.')
    return clave_mysql


def verificar_acceso(clave_mysql):
    with closing(MySQLdb.connect(
        **DESTINO, user=USUARIO, passwd=clave_mysql, db=BASE
    )) as conexion, closing(conexion.cursor()) as cursor:
        cursor.execute(SQL_VERIFICAR)
        version, base, cuenta = cursor.fetchone()
        if base != BASE or cuenta != f'{USUARIO}@127.0.0.1':
            raise SystemExit('La conexión no coincide con el destino.')
        print(f'Conexión verificada: MySQL {version}, {base}, {cuenta}.')
        cursor.execute('SHOW GRANTS')
        for (permiso,) in cursor.fetchall():
            print(permiso)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('modo', choices=('inspeccionar', 'crear'))
    modo = parser.parse_args().modo
    if not sys.stdin.isatty():
        raise SystemExit('Ejecuta el comando en una terminal interactiva.')
    if modo == 'crear' and not sys.stdout.isatty():
        raise SystemExit('Ejecuta crear sin redirigir ni registrar la salida.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            clave_root = getpass('Contraseña de MySQL root: ')
        try:
            conexion = MySQLdb.connect(
                **DESTINO, user='root', passwd=clave_root
            )
        finally:
            del clave_root
        with closing(conexion), closing(conexion.cursor()) as cursor:
            revocaciones_parciales = inspeccionar(cursor)
            if modo == 'inspeccionar':
                return
            clave_mysql = crear(cursor, revocaciones_parciales)
        verificar_acceso(clave_mysql)
    except MySQLdb.Error as error:
        codigo = error.args[0] if error.args else None
        codigo = codigo if isinstance(codigo, int) else 'desconocido'
        raise SystemExit(
            f'MySQL rechazó la operación. Código: {codigo}.'
        ) from None
    except (OSError, ValueError, GetPassWarning):
        raise SystemExit(
            'No se completó la preparación local de forma segura.'
        ) from None


if __name__ == '__main__':
    main()
