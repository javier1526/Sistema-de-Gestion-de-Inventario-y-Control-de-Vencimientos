"""Comprueba retiros simultáneos con un lote aislado en MySQL local."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import django
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone


def verificar_destino():
    configuracion = connection.settings_dict
    if (connection.vendor, configuracion['HOST'], str(configuracion['PORT'])) != (
        'mysql', '127.0.0.1', '3306',
    ):
        raise RuntimeError('La prueba requiere la conexión MySQL local prevista.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE(), CURRENT_USER(), VERSION(), @@port')
        if cursor.fetchone() != (
            'inventario_bodega', 'bodega_app@127.0.0.1', '8.4.13', 3306,
        ):
            raise RuntimeError('El destino de MySQL no coincide con el previsto.')
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND engine = 'InnoDB' "
            "AND table_name IN ('inventario_producto', 'inventario_lote', "
            "'inventario_movimiento')"
        )
        if cursor.fetchone() != (3,):
            raise RuntimeError('La prueba requiere las tres tablas de inventario InnoDB.')


def id_conexion():
    with connection.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        cursor.execute('SELECT CONNECTION_ID()')
        return cursor.fetchone()[0]


def comprobar_retiros():
    from inventario.models import Lote, Movimiento, Producto
    from inventario.servicios import registrar_retiro
    from usuarios.permisos import ADMINISTRADOR, REPONEDOR, obtener_perfil

    verificar_destino()
    usuarios = get_user_model().objects
    responsable = usuarios.get(username='reponedor')
    if obtener_perfil(responsable) != REPONEDOR or obtener_perfil(
        usuarios.get(username='administrador'),
    ) != ADMINISTRADOR:
        raise RuntimeError('Los perfiles de las cuentas locales no coinciden.')

    marca = f'Prueba concurrencia retiro {uuid4().hex}'
    with transaction.atomic():
        producto = Producto.objects.create(nombre=marca, stock_minimo=1)
        lote = Lote.objects.create(
            producto=producto, codigo_lote=marca, fecha_vencimiento=timezone.localdate(),
            cantidad_ingresada=8, cantidad_restante=8, costo_unitario_clp=500,
        )

    primero_escrito = Event()
    segundo_intenta_bloqueo = Event()
    liberar_primero = Event()
    movimientos_creados = []
    datos = dict(producto_id=producto.pk, lote_id=lote.pk, cantidad=6, responsable=responsable)

    def primer_retiro():
        try:
            identificador = id_conexion()
            with transaction.atomic():
                movimientos_creados.append(registrar_retiro(**datos).pk)
                primero_escrito.set()
                if not liberar_primero.wait(8):
                    raise RuntimeError('El primer retiro no recibió permiso para confirmar.')
            return identificador
        finally:
            connection.close()

    def avisar_bloqueo(execute, sql, params, many, context):
        if 'FOR UPDATE' in sql and 'inventario_lote' in sql:
            segundo_intenta_bloqueo.set()
        return execute(sql, params, many, context)

    def segundo_retiro():
        try:
            identificador = id_conexion()
            with connection.execute_wrapper(avisar_bloqueo):
                try:
                    movimientos_creados.append(registrar_retiro(**datos).pk)
                except ValidationError as error:
                    return identificador, error.code, error.params
            raise AssertionError('El segundo retiro se confirmó inesperadamente.')
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as trabajadores:
            primero = trabajadores.submit(primer_retiro)
            try:
                assert primero_escrito.wait(5), 'El primer retiro no obtuvo el bloqueo.'
                segundo = trabajadores.submit(segundo_retiro)
                assert segundo_intenta_bloqueo.wait(5), 'El segundo retiro no intentó bloquear el lote.'
                try:
                    segundo.result(timeout=0.25)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError('El segundo retiro no esperó el bloqueo.')
            finally:
                liberar_primero.set()
            conexion_primera = primero.result(timeout=10)
            conexion_segunda, codigo, parametros = segundo.result(timeout=10)

        assert conexion_primera != conexion_segunda
        assert codigo == 'saldo_insuficiente' and parametros == {'saldo': 2}
        lote.refresh_from_db()
        assert (lote.cantidad_restante, lote.cantidad_ingresada, lote.costo_unitario_clp) == (2, 8, 500)
        assert list(lote.movimientos.values_list('tipo', 'cantidad', 'responsable_id')) == [
            (Movimiento.Tipo.RETIRO, 6, responsable.pk),
        ]
        print(f'Conexiones distintas: {conexion_primera} y {conexion_segunda}.')
        print('Saldo inicial 8, retiros solicitados 6 y 6, saldo final 2.')
        print('Un retiro confirmado, uno rechazado con saldo 2 y un movimiento de retiro.')
    finally:
        with transaction.atomic():
            lote_aislado = Lote.objects.get(pk=lote.pk, producto=producto, codigo_lote=marca)
            Movimiento.objects.filter(lote=lote_aislado, pk__in=movimientos_creados).delete()
            lote_aislado.delete()
            Producto.objects.get(pk=producto.pk, nombre=marca).delete()
        print('Datos de prueba identificados y limpiados.')


if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sistema_inventario_bodega.settings')
    django.setup()
    comprobar_retiros()
