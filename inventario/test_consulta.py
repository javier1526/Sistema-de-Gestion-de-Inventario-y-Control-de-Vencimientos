from datetime import datetime, timedelta, timezone as zona_utc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.permisos import ADMINISTRADOR, REPONEDOR

from .lecturas import buscar_productos, consultar_lotes
from .models import Lote, Movimiento, Producto


class PruebasConsultaInventario(TestCase):
    @classmethod
    def setUpTestData(cls):
        modelo_usuario = get_user_model()
        cls.administrador = modelo_usuario.objects.create_user('admin_consulta')
        cls.reponedor = modelo_usuario.objects.create_user('reponedor_consulta')
        cls.sin_perfil = modelo_usuario.objects.create_user('sin_perfil_consulta')
        cls.ambiguo = modelo_usuario.objects.create_user('ambiguo_consulta')
        administrador = Group.objects.create(name=ADMINISTRADOR)
        reponedor = Group.objects.create(name=REPONEDOR)
        cls.administrador.groups.add(administrador)
        cls.reponedor.groups.add(reponedor)
        cls.ambiguo.groups.add(administrador, reponedor)
        cls.hoy = timezone.localdate()
        cls.cafe = Producto.objects.create(nombre='Café molido', stock_minimo=3)
        cls.otro = Producto.objects.create(nombre='Café instantáneo', stock_minimo=2)
        cls.sin_lotes = Producto.objects.create(nombre='Café descafeinado', stock_minimo=2)
        cls.solo_vencido = Producto.objects.create(nombre='Café en grano', stock_minimo=2)
        cls.solo_agotado = Producto.objects.create(nombre='Café de prueba', stock_minimo=2)
        cls.crear_lote(cls.cafe, 'POSTERIOR', 15, 3)
        cls.crear_lote(cls.cafe, 'HOY', 0, 2)
        cls.crear_lote(cls.cafe, 'PROXIMO', 5, 4)
        cls.crear_lote(cls.cafe, 'VENCIDO-UNIDADES', -1, 6)
        cls.agotado_vencido = cls.crear_lote(cls.cafe, 'AGOTADO-VENCIDO', -1, 0)
        cls.crear_lote(cls.cafe, 'AGOTADO-HOY', 0, 0)
        cls.crear_lote(cls.otro, 'OTRO-PRODUCTO', 1, 20)
        cls.crear_lote(cls.otro, 'OTRO-AGOTADO', -1, 0)
        cls.crear_lote(cls.solo_vencido, 'SOLO-VENCIDO', -1, 8)
        cls.crear_lote(cls.solo_agotado, 'SOLO-AGOTADO', 3, 0)
        Movimiento.objects.create(
            lote=cls.agotado_vencido, responsable=cls.administrador,
            tipo=Movimiento.Tipo.INGRESO, cantidad=10,
        )

    @classmethod
    def crear_lote(cls, producto, codigo, dias, saldo):
        return Lote.objects.create(
            producto=producto, codigo_lote=codigo,
            fecha_vencimiento=cls.hoy + timedelta(days=dias),
            cantidad_ingresada=max(10, saldo), cantidad_restante=saldo,
            costo_unitario_clp=250,
        )

    def setUp(self):
        self.buscar = reverse('consulta_inventario:buscar')
        self.detalle = reverse('consulta_inventario:producto', args=[self.cafe.pk])
        self.agotados = reverse('consulta_inventario:agotados', args=[self.cafe.pk])
        self.client.force_login(self.reponedor)
        parche = patch('inventario.vistas_consulta.timezone.localdate', return_value=self.hoy)
        parche.start()
        self.addCleanup(parche.stop)

    def test_ambos_perfiles_tienen_enlace_y_acceso_directo(self):
        for usuario in (self.administrador, self.reponedor):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.assertContains(self.client.get('/'), 'Consultar inventario')
                for ruta in (self.buscar, self.detalle, self.agotados):
                    self.assertEqual(self.client.get(ruta).status_code, 200)

    def test_anonimo_es_redirigido_y_perfil_invalido_recibe_403(self):
        for ruta in (self.buscar, self.detalle, self.agotados):
            with self.subTest(ruta=ruta):
                self.assertRedirects(
                    Client().get(ruta), f'/acceso/iniciar-sesion/?next={ruta}',
                    fetch_redirect_response=False,
                )
                for usuario in (self.sin_perfil, self.ambiguo):
                    self.client.force_login(usuario)
                    self.assertEqual(self.client.get(ruta).status_code, 403)

    def test_busqueda_por_nombre_completo_o_parcial_con_mayusculas_y_espacios(self):
        for termino in ('  CAFÉ MOLIDO  ', '  É MOL  ', 'molido'):
            with self.subTest(termino=termino):
                respuesta = self.client.get(self.buscar, {'q': termino})
                self.assertEqual([p.pk for p in respuesta.context['productos']], [self.cafe.pk])
                self.assertContains(respuesta, self.detalle)
        respuesta = self.client.get(self.buscar, {'q': ' café '})
        self.assertEqual(len(respuesta.context['productos']), 5)

    def test_busqueda_sin_coincidencias_muestra_mensaje_exacto(self):
        respuesta = self.client.get(self.buscar, {'q': 'xyz sin coincidencias'})
        self.assertContains(respuesta, 'role="status">No se encontraron productos</p>')
        self.assertFalse(respuesta.context['productos'])

    def test_sin_stock_en_resultados_para_los_tres_origenes(self):
        respuesta = self.client.get(self.buscar, {'q': 'café'})
        self.assertContains(respuesta, '>Sin stock</span>', count=3)
        sin_stock = {p.pk for p in respuesta.context['productos'] if p.stock_disponible == 0}
        self.assertEqual(sin_stock, {self.sin_lotes.pk, self.solo_vencido.pk, self.solo_agotado.pk})

    def test_producto_sin_lotes_es_consultable(self):
        ruta = reverse('consulta_inventario:producto', args=[self.sin_lotes.pk])
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Café descafeinado')
        self.assertContains(respuesta, 'Sin stock')
        producto = respuesta.context['producto']
        self.assertEqual((producto.stock_fisico, producto.stock_disponible), (0, 0))
        self.assertContains(respuesta, 'Ver lotes agotados')

    def test_fisico_incluye_vencidos_y_disponible_los_excluye(self):
        respuesta = self.client.get(self.detalle)
        producto = respuesta.context['producto']
        self.assertEqual((producto.stock_fisico, producto.stock_disponible), (15, 9))
        ruta = reverse('consulta_inventario:producto', args=[self.solo_vencido.pk])
        vencido = self.client.get(ruta)
        self.assertEqual((vencido.context['producto'].stock_fisico,
                          vencido.context['producto'].stock_disponible), (8, 0))
        self.assertContains(vencido, 'Sin stock')

    def test_fefo_ordenado_vencidos_visibles_y_agotados_excluidos(self):
        respuesta = self.client.get(self.detalle)
        self.assertEqual(
            [lote.codigo_lote for lote in respuesta.context['lotes_vigentes']],
            ['HOY', 'PROXIMO', 'POSTERIOR'],
        )
        self.assertEqual(
            [lote.codigo_lote for lote in respuesta.context['lotes_vencidos']],
            ['VENCIDO-UNIDADES'],
        )
        self.assertContains(respuesta, '>Vencido</span>')
        self.assertContains(respuesta, 'FEFO recomienda')
        self.assertNotContains(respuesta, 'AGOTADO-VENCIDO')
        self.assertNotContains(respuesta, 'OTRO-PRODUCTO')
        self.assertNotContains(respuesta, 'Café instantáneo')

    def test_lote_vigente_hoy_pasa_a_vencido_al_dia_siguiente_en_santiago(self):
        instante = datetime(2026, 11, 11, 2, 59, tzinfo=zona_utc.utc)
        Lote.objects.filter(producto=self.cafe, codigo_lote='HOY').update(
            fecha_vencimiento=datetime(2026, 11, 10).date(),
        )
        with patch('inventario.vistas_consulta.timezone.localdate', wraps=self.fecha_santiago):
            with patch('django.utils.timezone.now', return_value=instante):
                hoy = self.client.get(self.detalle)
            with patch('django.utils.timezone.now', return_value=instante + timedelta(minutes=1)):
                manana = self.client.get(self.detalle)
        self.assertIn('HOY', [lote.codigo_lote for lote in hoy.context['lotes_vigentes']])
        self.assertIn('HOY', [lote.codigo_lote for lote in manana.context['lotes_vencidos']])

    @staticmethod
    def fecha_santiago():
        return timezone.localtime().date()

    def test_agotados_aislados_con_doble_estado_y_retorno_al_producto(self):
        respuesta = self.client.get(self.agotados, {'q': 'café'})
        lotes = respuesta.context['lotes']
        self.assertEqual([(l.codigo_lote, l.vencido_en_consulta) for l in lotes], [
            ('AGOTADO-VENCIDO', True), ('AGOTADO-HOY', False),
        ])
        self.assertContains(respuesta, '>Agotado</span>', count=2)
        self.assertContains(respuesta, '>Vencido</span>', count=1)
        self.assertContains(respuesta, f'{self.detalle}?q=caf%C3%A9')
        self.assertNotContains(respuesta, 'OTRO-AGOTADO')
        self.assertNotContains(respuesta, 'VENCIDO-UNIDADES')

    def test_producto_sin_lotes_agotados_y_seleccion_invalida(self):
        ruta = reverse('consulta_inventario:agotados', args=[self.sin_lotes.pk])
        self.assertContains(self.client.get(ruta), 'No hay lotes agotados para este producto.')
        for ruta in ('/inventario/999999/', '/inventario/999999/agotados/', '/inventario/agotados/'):
            respuesta = self.client.get(ruta)
            self.assertContains(respuesta, 'Selecciona un producto válido', status_code=404)
            self.assertNotContains(respuesta, 'AGOTADO-VENCIDO', status_code=404)

    def test_consultas_no_modifican_registros_ni_admiten_post(self):
        def estado():
            return [list(modelo.objects.order_by('pk').values_list())
                    for modelo in (Producto, Lote, Movimiento)]

        antes = estado()
        for ruta in (self.buscar, self.detalle, self.agotados):
            self.assertEqual(self.client.get(ruta, {'q': 'café'}).status_code, 200)
            self.assertEqual(self.client.post(ruta, {'cantidad_restante': '0'}).status_code, 405)
        self.assertEqual(estado(), antes)

    def test_falla_de_lectura_no_presenta_existencias_confirmadas(self):
        with patch('inventario.vistas_consulta.consultar_lotes', side_effect=DatabaseError):
            respuesta = self.client.get(self.detalle)
        self.assertContains(respuesta, 'No se pudo completar la consulta.', status_code=503)
        self.assertNotContains(respuesta, 'stock-fisico', status_code=503)

    def test_lecturas_en_bloque_sin_consultas_por_producto_o_lote(self):
        with self.assertNumQueries(2):
            resultados = list(buscar_productos('café', self.hoy))
            self.assertEqual(len([p.stock_disponible for p in resultados]), 5)
        with self.assertNumQueries(1):
            lotes = consultar_lotes(self.cafe, self.hoy)
            self.assertEqual(len([lote.vencido_en_consulta for lote in lotes]), 4)
