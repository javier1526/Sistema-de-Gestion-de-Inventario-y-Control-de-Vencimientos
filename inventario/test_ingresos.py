from datetime import datetime, timedelta, timezone as zona_utc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.permisos import ADMINISTRADOR, REPONEDOR

from .models import Lote, Movimiento, Producto
from .servicios import registrar_ingreso


class PruebasIngresosPorLote(TestCase):
    @classmethod
    def setUpTestData(cls):
        usuario = get_user_model()
        cls.administrador = usuario.objects.create_user('admin_ingresos')
        cls.administrador.groups.add(Group.objects.create(name=ADMINISTRADOR))
        cls.reponedor = usuario.objects.create_user('reponedor_ingresos')
        cls.reponedor.groups.add(Group.objects.create(name=REPONEDOR))
        cls.producto = Producto.objects.create(nombre='Arroz', stock_minimo=5)

    def setUp(self):
        self.ruta = reverse('inventario:ingresar_lote')
        self.hoy = timezone.localdate()
        self.datos = {
            'producto': self.producto.pk,
            'codigo_lote': 'AL-01',
            'fecha_vencimiento': (self.hoy + timedelta(days=8)).isoformat(),
            'cantidad_ingresada': '12',
            'costo_unitario_clp': '850',
        }
        self.client.force_login(self.administrador)

    def ingresar(self, **cambios):
        return self.client.post(self.ruta, {**self.datos, **cambios}, follow=True)

    def comprobar_ingreso_rechazado(self):
        self.assertFalse(Lote.objects.exists())
        self.assertFalse(Movimiento.objects.exists())
        self.assertEqual(self.producto.calcular_stock_fisico(), 0)

    def test_ingreso_guarda_lote_y_movimiento_trazable(self):
        antes = timezone.now()
        respuesta = self.ingresar(codigo_lote='  AL-01 ', responsable=self.reponedor.pk)
        self.assertContains(respuesta, 'El lote y su ingreso se registraron correctamente.')
        lote = Lote.objects.get()
        movimiento = Movimiento.objects.get()
        self.assertIsNotNone(lote.pk)
        self.assertIsNotNone(movimiento.pk)
        self.assertEqual(lote.producto_id, self.producto.pk)
        self.assertEqual(lote.codigo_lote, 'AL-01')
        self.assertEqual(lote.fecha_vencimiento, self.hoy + timedelta(days=8))
        self.assertEqual((lote.cantidad_ingresada, lote.cantidad_restante), (12, 12))
        self.assertEqual(lote.costo_unitario_clp, 850)
        self.assertEqual(movimiento.tipo, Movimiento.Tipo.INGRESO)
        self.assertEqual(movimiento.cantidad, 12)
        self.assertEqual(movimiento.responsable_id, self.administrador.pk)
        self.assertEqual(movimiento.lote_id, lote.pk)
        self.assertEqual(movimiento.lote.producto_id, self.producto.pk)
        self.assertEqual(movimiento.lote.codigo_lote, 'AL-01')
        self.assertLessEqual(antes, movimiento.fecha_hora)
        self.assertLessEqual(movimiento.fecha_hora, timezone.now())

    def test_rechaza_producto_inexistente(self):
        self.assertContains(self.ingresar(producto=99999), 'El producto seleccionado no existe.')
        self.comprobar_ingreso_rechazado()

    def test_todos_los_campos_son_obligatorios(self):
        for campo in self.datos:
            with self.subTest(campo=campo):
                respuesta = self.ingresar(**{campo: ''})
                self.assertTrue(respuesta.context['formulario'].has_error(campo, 'required'))
                self.comprobar_ingreso_rechazado()

    def test_codigo_compuesto_solo_por_espacios_es_vacio(self):
        self.assertContains(self.ingresar(codigo_lote='  \t '), 'Indica el código de lote.')
        self.comprobar_ingreso_rechazado()

    def test_duplicado_del_mismo_producto_aunque_cambie_la_fecha(self):
        self.ingresar(codigo_lote=' AL-01 ')
        respuesta = self.ingresar(
            codigo_lote='al-01  ', fecha_vencimiento=(self.hoy + timedelta(days=30)).isoformat(),
        )
        self.assertContains(respuesta, 'Ya existe un lote con ese código para este producto.')
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Movimiento.objects.count(), 1)
        self.assertEqual(self.producto.calcular_stock_fisico(), 12)

    def test_codigo_puede_repetirse_en_otro_producto(self):
        otro = Producto.objects.create(nombre='Fideos', stock_minimo=2)
        self.ingresar()
        self.ingresar(producto=otro.pk, codigo_lote=' al-01 ')
        self.assertEqual(Lote.objects.count(), 2)
        self.assertEqual(Movimiento.objects.count(), 2)

    def test_normalizacion_conserva_espacios_internos(self):
        self.ingresar(codigo_lote='AB  12')
        self.ingresar(codigo_lote='AB 12')
        self.assertCountEqual(Lote.objects.values_list('codigo_lote', flat=True), ['AB  12', 'AB 12'])

    def test_fecha_anterior_a_hoy_se_rechaza(self):
        respuesta = self.ingresar(fecha_vencimiento=(self.hoy - timedelta(days=1)).isoformat())
        self.assertContains(respuesta, 'La fecha de vencimiento no puede ser anterior a hoy.')
        self.comprobar_ingreso_rechazado()

    def test_vencimiento_hoy_usa_fecha_local_y_solo_vence_al_dia_siguiente(self):
        instante = datetime(2026, 11, 11, 1, tzinfo=zona_utc.utc)
        with timezone.override('America/Santiago'), patch('django.utils.timezone.now', return_value=instante):
            self.assertEqual(timezone.localdate().isoformat(), '2026-11-10')
            self.ingresar(fecha_vencimiento='2026-11-10')
            lote = Lote.objects.get()
            self.assertFalse(lote.esta_vencido())
        self.assertTrue(lote.esta_vencido(lote.fecha_vencimiento + timedelta(days=1)))

    def test_cantidad_y_costo_deben_ser_enteros_positivos(self):
        for campo in ('cantidad_ingresada', 'costo_unitario_clp'):
            for valor in ('0', '-2', '2.5', '2.0', 'texto', '1e2'):
                with self.subTest(campo=campo, valor=valor):
                    respuesta = self.ingresar(**{campo: valor})
                    self.assertIn('entero mayor que cero', respuesta.context['formulario'].errors[campo][0])
                    self.comprobar_ingreso_rechazado()

    def test_lotes_distintos_suman_existencias_y_conservan_costos(self):
        self.ingresar()
        anterior = Lote.objects.get()
        self.ingresar(codigo_lote='AL-02', cantidad_ingresada='7', costo_unitario_clp='650')
        anterior.refresh_from_db()
        self.assertEqual((anterior.cantidad_ingresada, anterior.cantidad_restante), (12, 12))
        self.assertEqual(anterior.costo_unitario_clp, 850)
        self.assertEqual(self.producto.calcular_stock_fisico(), 19)
        self.assertEqual(self.producto.lotes.count(), 2)
        self.assertEqual(Movimiento.objects.count(), 2)

    def test_falla_al_guardar_movimiento_revierte_lote_y_stock(self):
        self.ingresar()
        crear_movimiento = Movimiento.objects.create

        def fallar_despues_de_escribir(**datos):
            crear_movimiento(**datos)
            raise DatabaseError

        with patch.object(Movimiento.objects, 'create', side_effect=fallar_despues_de_escribir):
            respuesta = self.ingresar(codigo_lote='FALLA')
        self.assertContains(respuesta, 'No se pudo registrar el ingreso.')
        self.assertEqual(self.producto.calcular_stock_fisico(), 12)
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Movimiento.objects.count(), 1)

    def test_conflicto_detectado_por_indice_unico_se_informa_como_duplicado(self):
        self.ingresar()
        with patch.object(Lote, 'codigo_ya_registrado', side_effect=[False, True]):
            respuesta = self.ingresar(codigo_lote=' al-01 ')
        self.assertContains(respuesta, 'Ya existe un lote con ese código para este producto.')
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Movimiento.objects.count(), 1)
        self.assertEqual(self.producto.calcular_stock_fisico(), 12)

    def test_base_protege_unicidad_y_rangos_del_lote(self):
        self.ingresar()
        lote = Lote.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lote.objects.create(
                producto=self.producto, codigo_lote=' al-01 ', fecha_vencimiento=self.hoy,
                cantidad_ingresada=1, cantidad_restante=1, costo_unitario_clp=1,
            )
        for campos in (
            {'cantidad_restante': -1}, {'cantidad_restante': 13},
            {'cantidad_ingresada': 0, 'cantidad_restante': 0}, {'costo_unitario_clp': 0},
        ):
            with self.subTest(campos=campos), self.assertRaises(IntegrityError), transaction.atomic():
                Lote.objects.filter(pk=lote.pk).update(**campos)
        lote.refresh_from_db()
        self.assertEqual(lote.cantidad_restante, 12)

    def test_permisos_en_vista_y_servicio(self):
        self.assertContains(self.client.get('/'), 'Registrar ingreso por lote')
        anonimo = Client()
        self.assertEqual(anonimo.get(self.ruta).status_code, 302)
        self.assertEqual(anonimo.post(self.ruta, self.datos).status_code, 302)
        self.client.force_login(self.reponedor)
        self.assertNotContains(self.client.get('/'), 'Registrar ingreso por lote')
        self.assertEqual(self.client.get(self.ruta).status_code, 403)
        self.assertEqual(self.client.post(self.ruta, self.datos).status_code, 403)
        with self.assertRaises(PermissionDenied):
            registrar_ingreso(Lote(producto=self.producto), self.reponedor)
        self.comprobar_ingreso_rechazado()

    def test_csrf_y_cancelacion_no_guardan(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.administrador)
        self.assertContains(cliente.get(self.ruta), 'href="/">Cancelar')
        self.assertEqual(cliente.get('/').status_code, 200)
        self.assertEqual(cliente.post(self.ruta, self.datos).status_code, 403)
        self.comprobar_ingreso_rechazado()

    def test_editar_producto_con_historial_conserva_relaciones(self):
        self.ingresar()
        movimiento = Movimiento.objects.get()
        editar = reverse('inventario:editar_producto', args=[self.producto.pk])
        respuesta = self.client.post(editar, {'nombre': 'Arroz integral', 'stock_minimo': '9'})
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        movimiento.refresh_from_db()
        self.assertEqual(self.producto.stock_minimo, 9)
        self.assertEqual(movimiento.lote.producto_id, self.producto.pk)
        self.assertEqual(movimiento.lote.producto.nombre, 'Arroz integral')
        self.assertEqual(movimiento.lote.codigo_lote, 'AL-01')
        self.assertEqual(movimiento.cantidad, 12)

    def test_historial_real_protege_producto_incluso_con_lote_agotado(self):
        self.ingresar()
        lote = Lote.objects.get()
        eliminar = reverse('inventario:eliminar_producto', args=[self.producto.pk])
        for saldo in (12, 0):
            with self.subTest(saldo=saldo):
                Lote.objects.filter(pk=lote.pk).update(cantidad_restante=saldo)
                respuesta = self.client.post(eliminar, {'confirmar': 'si'}, follow=True)
                self.assertContains(respuesta, 'tiene historial de inventario')
                self.assertTrue(Producto.objects.filter(pk=self.producto.pk).exists())
                self.assertTrue(Movimiento.objects.filter(lote=lote).exists())
        with self.assertRaises(ProtectedError):
            lote.delete()

    def test_producto_sin_antecedentes_se_puede_eliminar(self):
        eliminar = reverse('inventario:eliminar_producto', args=[self.producto.pk])
        self.assertContains(self.client.get(eliminar), 'Confirmar eliminación')
        respuesta = self.client.post(eliminar, {'confirmar': 'si'}, follow=True)
        self.assertContains(respuesta, 'Producto eliminado correctamente.')
        self.assertFalse(Producto.objects.filter(pk=self.producto.pk).exists())
