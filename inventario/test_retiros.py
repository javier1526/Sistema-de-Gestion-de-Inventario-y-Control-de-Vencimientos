from datetime import datetime, timedelta, timezone as zona_utc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.permisos import ADMINISTRADOR, REPONEDOR

from .models import Lote, Movimiento, Producto


class PruebasRetiros(TestCase):
    @classmethod
    def setUpTestData(cls):
        usuarios = get_user_model()
        grupo_reponedor = Group.objects.create(name=REPONEDOR)
        grupo_administrador = Group.objects.create(name=ADMINISTRADOR)
        cls.reponedor = usuarios.objects.create_user('reponedor_retiros')
        cls.reponedor.groups.add(grupo_reponedor)
        cls.administrador = usuarios.objects.create_user('admin_retiros')
        cls.administrador.groups.add(grupo_administrador)
        cls.ambiguo = usuarios.objects.create_user('ambiguo_retiros')
        cls.ambiguo.groups.add(grupo_administrador, grupo_reponedor)
        cls.sin_perfil = usuarios.objects.create_user('sin_perfil_retiros')

        cls.hoy = timezone.localdate()
        cls.producto = Producto.objects.create(nombre='Café', stock_minimo=4)
        cls.otro_producto = Producto.objects.create(nombre='Arroz', stock_minimo=4)
        cls.hoy_lote = cls.crear_lote('HOY', 0, 4)
        cls.lote = cls.crear_lote('SIGUIENTE', 3, 8)
        cls.vencido = cls.crear_lote('VENCIDO', -1, 3)
        cls.agotado = cls.crear_lote('AGOTADO', 3, 0)
        cls.ajeno = cls.crear_lote('AJENO', 3, 10, cls.otro_producto)
        cls.ingreso = Movimiento.objects.create(
            lote=cls.lote, responsable=cls.administrador,
            tipo=Movimiento.Tipo.INGRESO, cantidad=10,
        )

    @classmethod
    def crear_lote(cls, codigo, dias, saldo, producto=None):
        return Lote.objects.create(
            producto=producto or cls.producto, codigo_lote=codigo,
            fecha_vencimiento=cls.hoy + timedelta(days=dias),
            cantidad_ingresada=10, cantidad_restante=saldo, costo_unitario_clp=500,
        )

    def setUp(self):
        self.client.force_login(self.reponedor)
        self.detalle = reverse('consulta_inventario:producto', args=[self.producto.pk])
        self.agotados = reverse('consulta_inventario:agotados', args=[self.producto.pk])
        self.ruta = self.ruta_retiro(self.lote)

    def ruta_retiro(self, lote, producto=None):
        return reverse('consulta_inventario:retirar', args=[
            (producto or self.producto).pk, lote.pk,
        ])

    def confirmar(self, cantidad, ruta=None, **extra):
        return self.client.post(ruta or self.ruta, {'cantidad': cantidad, **extra})

    def verificar_rechazo_sin_escrituras(self):
        self.assertEqual(Movimiento.objects.count(), 1)
        self.assertTrue(Movimiento.objects.filter(pk=self.ingreso.pk).exists())
        self.assertEqual(list(Lote.objects.order_by('pk').values_list(
            'cantidad_restante', flat=True,
        )), [4, 8, 3, 0, 10])

    def test_retiro_parcial_de_lote_distinto_de_fefo_y_trazabilidad(self):
        antes = timezone.now()
        respuesta = self.confirmar(
            '3', self.ruta + '?q=caf%C3%A9',
            lote=self.hoy_lote.pk, cantidad_restante=100, responsable=self.administrador.pk,
        )
        self.assertRedirects(respuesta, self.detalle + '?q=caf%C3%A9')
        self.lote.refresh_from_db()
        self.hoy_lote.refresh_from_db()
        self.assertEqual((self.lote.cantidad_restante, self.hoy_lote.cantidad_restante), (5, 4))
        self.assertEqual((self.lote.cantidad_ingresada, self.lote.costo_unitario_clp), (10, 500))
        self.assertEqual(Movimiento.objects.count(), 2)
        retiro = Movimiento.objects.get(tipo=Movimiento.Tipo.RETIRO)
        self.assertEqual((retiro.cantidad, retiro.responsable_id), (3, self.reponedor.pk))
        self.assertEqual(retiro.lote_id, self.lote.pk)
        self.assertEqual((retiro.lote.producto_id, retiro.lote.codigo_lote), (self.producto.pk, 'SIGUIENTE'))
        self.assertLessEqual(antes, retiro.fecha_hora)
        self.assertLessEqual(retiro.fecha_hora, timezone.now())
        detalle = self.client.get(self.detalle)
        self.assertEqual(detalle.context['producto'].stock_fisico, 12)
        self.assertEqual(detalle.context['producto'].stock_disponible, 9)
        self.producto.nombre = 'Café molido'
        self.producto.save(update_fields=['nombre'])
        self.assertEqual(Movimiento.objects.get(pk=retiro.pk).lote.producto.nombre, 'Café molido')

    def test_retiro_total_muestra_confirmacion_y_mueve_lote_a_agotados(self):
        respuesta = self.confirmar('8')
        self.assertEqual(respuesta.status_code, 302)
        detalle = self.client.get(respuesta.url)
        self.assertContains(detalle, 'El retiro se registró correctamente.')
        self.assertNotContains(detalle, 'Lote SIGUIENTE')
        self.assertContains(self.client.get(self.agotados), 'Lote SIGUIENTE')
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_restante, 0)
        self.assertEqual(self.lote.movimientos.count(), 2)

    def test_exceso_informa_el_saldo_actual_y_no_descuenta(self):
        respuesta = self.confirmar('10')
        self.assertContains(respuesta, 'Solo hay 8 unidades disponibles')
        self.verificar_rechazo_sin_escrituras()

    def test_lote_vencido_o_agotado_no_presenta_formulario_y_rechaza_post(self):
        casos = ((self.vencido, 'El lote está vencido.'),
                 (self.agotado, 'Solo hay 0 unidades disponibles'))
        for lote, mensaje in casos:
            with self.subTest(lote=lote.codigo_lote):
                ruta = self.ruta_retiro(lote)
                self.assertNotContains(self.client.get(ruta), 'Confirmar retiro')
                self.assertContains(self.confirmar('1', ruta), mensaje)
        self.verificar_rechazo_sin_escrituras()

    def test_vencimiento_cambia_a_medianoche_local_entre_formulario_y_post(self):
        antes = datetime(2026, 11, 11, 2, 59, tzinfo=zona_utc.utc)
        self.hoy_lote.fecha_vencimiento = datetime(2026, 11, 10).date()
        self.hoy_lote.save(update_fields=['fecha_vencimiento'])
        ruta = self.ruta_retiro(self.hoy_lote)
        with timezone.override('America/Santiago'):
            with patch('django.utils.timezone.now', return_value=antes):
                self.assertContains(self.client.get(ruta), 'Confirmar retiro')
                self.assertEqual(self.confirmar('1', ruta).status_code, 302)
            with patch('django.utils.timezone.now', return_value=antes + timedelta(minutes=1)):
                self.assertContains(self.confirmar('1', ruta), 'El lote está vencido.')
        self.hoy_lote.refresh_from_db()
        self.assertEqual(self.hoy_lote.cantidad_restante, 3)
        self.assertEqual(self.hoy_lote.movimientos.count(), 1)

    def test_cantidades_invalidas_no_generan_movimientos(self):
        for cantidad in ('', ' ', '0', '-2', '2.5', '2.0', 'abc', '1e1'):
            with self.subTest(cantidad=cantidad):
                respuesta = self.confirmar(cantidad)
                self.assertTrue(respuesta.context['formulario'].errors.get('cantidad'))
        self.verificar_rechazo_sin_escrituras()

    def test_identificadores_inexistentes_y_lote_de_otro_producto(self):
        rutas = (
            self.ruta_retiro(self.ajeno),
            reverse('consulta_inventario:retirar', args=[999999, self.lote.pk]),
            reverse('consulta_inventario:retirar', args=[self.producto.pk, 999999]),
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 404)
                self.assertEqual(self.confirmar('1', ruta).status_code, 404)
        self.verificar_rechazo_sin_escrituras()

    def test_fallo_despues_de_escribir_movimiento_revierte_ambas_escrituras(self):
        crear = Movimiento.objects.create

        def guardar_y_fallar(**datos):
            crear(**datos)
            raise DatabaseError

        with patch.object(Movimiento.objects, 'create', side_effect=guardar_y_fallar):
            self.assertContains(self.confirmar('3'), 'No se pudo registrar el retiro.')
        self.verificar_rechazo_sin_escrituras()

    def test_dos_confirmaciones_sucesivas_revalidan_saldo(self):
        self.client.get(self.ruta)
        otro_cliente = Client()
        otro_cliente.force_login(self.reponedor)
        otro_cliente.get(self.ruta)
        self.assertEqual(self.confirmar('6').status_code, 302)
        self.assertContains(otro_cliente.post(self.ruta, {'cantidad': 6}), 'Solo hay 2 unidades')
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_restante, 2)
        self.assertEqual(Movimiento.objects.filter(tipo=Movimiento.Tipo.RETIRO).count(), 1)

    def test_perfiles_y_acceso_directo(self):
        self.assertContains(self.client.get(self.detalle), 'Retirar unidades', count=2)
        self.assertNotContains(self.client.get(self.agotados), 'Retirar unidades')
        for usuario in (self.administrador, self.ambiguo, self.sin_perfil):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.ruta).status_code, 403)
                self.assertEqual(self.confirmar('1').status_code, 403)
        self.client.force_login(self.administrador)
        self.assertNotContains(self.client.get(self.detalle), 'Retirar unidades')
        self.client.logout()
        self.assertRedirects(self.client.get(self.ruta), f'/acceso/iniciar-sesion/?next={self.ruta}')
        self.assertEqual(self.confirmar('1').status_code, 302)
        self.verificar_rechazo_sin_escrituras()

    def test_cancelar_y_proteccion_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.reponedor)
        formulario = cliente.get(self.ruta)
        self.assertContains(formulario, f'href="{self.detalle}">Cancelar')
        self.assertEqual(cliente.get(self.detalle).status_code, 200)
        self.assertEqual(cliente.post(self.ruta, {'cantidad': 1}).status_code, 403)
        self.verificar_rechazo_sin_escrituras()
        token = cliente.cookies['csrftoken'].value
        respuesta = cliente.post(self.ruta, {'cantidad': 1, 'csrfmiddlewaretoken': token})
        self.assertEqual(respuesta.status_code, 302)
