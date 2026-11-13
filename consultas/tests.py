from datetime import datetime, timedelta, timezone as zona_utc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from inventario.models import Lote, Movimiento, Producto
from inventario.servicios import registrar_ingreso, registrar_retiro
from usuarios.permisos import ADMINISTRADOR, REPONEDOR

from .lecturas import alertas_stock, analizar_vencimientos, historial_movimientos


class PruebasConsultasAdministrativas(TestCase):
    @classmethod
    def setUpTestData(cls):
        administrador = Group.objects.create(name=ADMINISTRADOR)
        reponedor = Group.objects.create(name=REPONEDOR)
        usuarios = get_user_model().objects
        cls.administrador = usuarios.create_user('admin_consultas')
        cls.administrador.groups.add(administrador)
        cls.reponedor = usuarios.create_user('reponedor_consultas')
        cls.reponedor.groups.add(reponedor)
        cls.sin_perfil = usuarios.create_user('sin_perfil_consultas')
        cls.ambos = usuarios.create_user('ambos_consultas')
        cls.ambos.groups.add(administrador, reponedor)
        cls.hoy = timezone.localdate()

    def setUp(self):
        self.client.force_login(self.administrador)
        self.alertas = reverse('consultas:alertas')
        self.historial = reverse('consultas:historial')
        self.vencimientos = reverse('consultas:vencimientos')

    def producto(self, nombre='Café', minimo=5):
        return Producto.objects.create(nombre=nombre, stock_minimo=minimo)

    def lote(self, producto, codigo, dias, saldo=8, costo=1500):
        return Lote.objects.create(
            producto=producto, codigo_lote=codigo,
            fecha_vencimiento=self.hoy + timedelta(days=dias),
            cantidad_ingresada=max(saldo, 10), cantidad_restante=saldo,
            costo_unitario_clp=costo,
        )

    def retirar(self, lote, cantidad):
        return registrar_retiro(
            producto_id=lote.producto_id, lote_id=lote.pk,
            cantidad=cantidad, responsable=self.reponedor,
        )

    def movimiento(self, lote, tipo, responsable, cantidad):
        return Movimiento.objects.create(
            lote=lote, tipo=tipo, responsable=responsable, cantidad=cantidad,
        )

    def test_alertas_umbral_inclusivo_sin_duplicar_y_con_saldo_cero(self):
        inferior = self.producto('Té')
        igual = self.producto('Café')
        superior = self.producto('Leche')
        sin_lotes = self.producto('Sal')
        vencido = self.producto('Harina')
        self.lote(inferior, 'BAJO', 5, saldo=4)
        self.lote(igual, 'IGUAL-1', 0, saldo=3)
        self.lote(igual, 'IGUAL-2', 5, saldo=2)
        self.lote(igual, 'VENCIDO-1', -1, saldo=100)
        self.lote(superior, 'ALTO', 3, saldo=6)
        self.lote(vencido, 'VENCIDO-2', -1, saldo=12)
        respuesta = self.client.get(self.alertas)
        self.assertCountEqual(
            [(p.pk, p.stock_disponible) for p in respuesta.context['productos']],
            [(inferior.pk, 4), (igual.pk, 5), (sin_lotes.pk, 0), (vencido.pk, 0)],
        )
        self.assertContains(respuesta, '>Café</h2>', count=1)
        self.assertContains(respuesta, 'Stock mínimo')

    def test_ingreso_quita_alerta_y_retiro_la_reincorpora(self):
        producto = self.producto()
        self.assertContains(self.client.get(self.alertas), 'Café')
        lote = Lote(
            producto=producto, codigo_lote='ING-1', fecha_vencimiento=self.hoy,
            cantidad_ingresada=8, costo_unitario_clp=700,
        )
        registrar_ingreso(lote, self.administrador)
        self.assertContains(self.client.get(self.alertas), 'No hay alertas de stock mínimo.')
        self.retirar(lote, 3)
        self.assertEqual(self.client.get(self.alertas).context['productos'][0].stock_disponible, 5)

    def test_alerta_se_actualiza_por_vencimiento_y_cambio_del_minimo(self):
        producto = self.producto()
        self.lote(producto, 'VENCE', 0, saldo=6)
        self.assertFalse(self.client.get(self.alertas).context['productos'])
        producto.stock_minimo = 6
        producto.save(update_fields=['stock_minimo'])
        alerta = self.client.get(self.alertas).context['productos'][0]
        self.assertEqual((alerta.stock_disponible, alerta.stock_minimo), (6, 6))
        producto.stock_minimo = 5
        producto.save(update_fields=['stock_minimo'])
        self.assertFalse(self.client.get(self.alertas).context['productos'])
        with patch('django.utils.timezone.localdate', return_value=self.hoy + timedelta(days=1)):
            self.assertEqual(self.client.get(self.alertas).context['productos'][0].stock_disponible, 0)

    def test_alertas_sin_productos_muestra_estado_vacio(self):
        self.assertContains(self.client.get(self.alertas), 'No hay alertas de stock mínimo.')

    def test_historial_muestra_ambos_tipos_y_seis_datos_en_hora_local(self):
        producto = self.producto()
        lote = self.lote(producto, 'LOTE-ABC', 5)
        instante = datetime(2026, 11, 11, 2, 4, 5, tzinfo=zona_utc.utc)
        with patch('django.utils.timezone.now', return_value=instante):
            ingreso = self.movimiento(lote, Movimiento.Tipo.INGRESO, self.administrador, 10)
            retiro = self.movimiento(lote, Movimiento.Tipo.RETIRO, self.reponedor, 3)
        with timezone.override('America/Santiago'):
            respuesta = self.client.get(self.historial)
        self.assertEqual([m.pk for m in respuesta.context['movimientos']], [retiro.pk, ingreso.pk])
        for texto in ('10/11/2026 23:04:05', 'admin_consultas', 'reponedor_consultas',
                      'Café', 'LOTE-ABC', '>Ingreso<', '>Retiro<', '>10<', '>3<'):
            self.assertContains(respuesta, texto)

    def test_historial_vacio_y_con_un_solo_tipo(self):
        self.assertContains(self.client.get(self.historial), 'Todavía no hay movimientos registrados.')
        lote = self.lote(self.producto(), 'LOTE-1', 1)
        ingreso = self.movimiento(lote, Movimiento.Tipo.INGRESO, self.administrador, 10)
        self.assertEqual(self.client.get(self.historial).context['movimientos'], [ingreso])
        ingreso.delete()
        retiro = self.retirar(lote, 1)
        self.assertEqual(self.client.get(self.historial).context['movimientos'], [retiro])

    def test_historial_conserva_ingreso_y_nombre_vigente_sin_intentos_rechazados(self):
        producto = self.producto()
        lote = Lote(
            producto=producto, codigo_lote='ING-1', fecha_vencimiento=self.hoy,
            cantidad_ingresada=8, costo_unitario_clp=700,
        )
        ingreso = registrar_ingreso(lote, self.administrador)
        with self.assertRaises(ValidationError):
            self.retirar(lote, 9)
        with self.assertRaises(ValidationError):
            registrar_ingreso(lote, self.administrador)
        producto.nombre = 'Café renombrado'
        producto.save(update_fields=['nombre'])
        respuesta = self.client.get(self.historial)
        self.assertContains(respuesta, 'Café renombrado')
        self.assertEqual(respuesta.context['movimientos'], [ingreso])
        self.assertEqual(ingreso.lote.producto_id, producto.pk)

    def test_intervalos_limites_y_calculo_sin_duplicados(self):
        producto = self.producto()
        for dias in (-1, 0, 30, 31, 60, 61, 90, 91):
            self.lote(producto, f'DIAS-{dias}', dias, costo=1500 + max(0, dias))
        self.lote(producto, 'AGOTADO', 5, saldo=0)
        respuesta = self.client.get(self.vencimientos)
        intervalos = respuesta.context['intervalos']
        self.assertEqual([[d['dias'] for d in b['detalles']] for b in intervalos],
                         [[0, 30], [31, 60], [61, 90]])
        self.assertEqual([b['subtotal'] for b in intervalos], [24240, 24728, 25208])
        self.assertEqual(respuesta.context['total'], 74176)
        self.assertContains(respuesta, '$74.176 CLP')
        self.assertContains(respuesta, '$12.000 CLP')
        self.assertContains(respuesta, 'Café')
        self.assertContains(respuesta, 'DIAS-0')
        self.assertContains(respuesta, 'Días restantes')
        for codigo in ('DIAS--1', 'DIAS-91', 'AGOTADO'):
            self.assertNotContains(respuesta, codigo)

    def test_intervalos_vacios_y_valor_actualizado_tras_retiro(self):
        respuesta = self.client.get(self.vencimientos)
        self.assertEqual(respuesta.context['total'], 0)
        self.assertContains(respuesta, 'Subtotal $0 CLP', count=3)
        lote = self.lote(self.producto(), 'RIESGO', 31)
        self.assertEqual(self.client.get(self.vencimientos).context['total'], 12000)
        self.retirar(lote, 3)
        respuesta = self.client.get(self.vencimientos)
        self.assertEqual([b['subtotal'] for b in respuesta.context['intervalos']], [0, 7500, 0])
        self.assertEqual(respuesta.context['total'], 7500)
        lote.refresh_from_db()
        self.assertEqual(lote.costo_unitario_clp, 1500)
        self.retirar(lote, 5)
        self.assertEqual(self.client.get(self.vencimientos).context['total'], 0)

    def test_permisos_en_inicio_y_urls_directas(self):
        rutas = (self.alertas, self.historial, self.vencimientos)
        for ruta in rutas:
            self.assertContains(self.client.get('/'), f'href="{ruta}"')
            self.assertEqual(self.client.get(ruta).status_code, 200)
            self.assertEqual(Client().get(ruta).status_code, 302)
        for usuario in (self.reponedor, self.sin_perfil, self.ambos):
            self.client.force_login(usuario)
            for ruta in rutas:
                with self.subTest(usuario=usuario.username, ruta=ruta):
                    self.assertEqual(self.client.get(ruta).status_code, 403)
        self.client.force_login(self.reponedor)
        for ruta in rutas:
            self.assertNotContains(self.client.get('/'), f'href="{ruta}"')

    def test_consultas_de_solo_lectura(self):
        lote = self.lote(self.producto(), 'LOTE-1', 1)
        self.retirar(lote, 1)

        def estado():
            return [list(modelo.objects.order_by('pk').values_list())
                    for modelo in (Producto, Lote, Movimiento)]

        antes = estado()
        for ruta in (self.alertas, self.historial, self.vencimientos):
            self.assertEqual(self.client.get(ruta).status_code, 200)
            self.assertEqual(self.client.head(ruta).status_code, 200)
            self.assertEqual(self.client.post(ruta, {'cantidad': 2}).status_code, 405)
        self.assertEqual(estado(), antes)

    def test_una_lectura_de_dominio_por_consulta_incluso_con_relaciones(self):
        for nombre in ('Café', 'Té'):
            lote = self.lote(self.producto(nombre), 'LOTE-1', 1)
            self.retirar(lote, 3)
        with self.assertNumQueries(1):
            self.assertEqual(len(alertas_stock()['productos']), 2)
        with self.assertNumQueries(1):
            filas = historial_movimientos()['movimientos']
            self.assertEqual({m.lote.producto.nombre for m in filas}, {'Café', 'Té'})
            self.assertTrue(all(m.responsable.username for m in filas))
        with self.assertNumQueries(1):
            detalles = analizar_vencimientos()['intervalos'][0]['detalles']
            self.assertEqual({d['lote'].producto.nombre for d in detalles}, {'Café', 'Té'})

    def test_fallo_de_lectura_muestra_error_y_no_totales_confirmados(self):
        for ruta, lectura in ((self.alertas, 'alertas_stock'),
                              (self.historial, 'historial_movimientos'),
                              (self.vencimientos, 'analizar_vencimientos')):
            with self.subTest(ruta=ruta), patch(f'consultas.views.{lectura}', side_effect=DatabaseError):
                respuesta = self.client.get(ruta)
                self.assertContains(respuesta, 'No se pudo completar la consulta.', status_code=503)
                self.assertNotContains(respuesta, 'total-riesgo', status_code=503)
