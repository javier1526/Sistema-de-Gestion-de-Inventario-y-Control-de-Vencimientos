from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from usuarios.permisos import ADMINISTRADOR, REPONEDOR

from .models import Producto


class PruebasGestionProductos(TestCase):
    @classmethod
    def setUpTestData(cls):
        modelo_usuario = get_user_model()
        cls.administrador = modelo_usuario.objects.create_user('admin_catalogo')
        cls.administrador.groups.add(Group.objects.create(name=ADMINISTRADOR))
        cls.reponedor = modelo_usuario.objects.create_user('reponedor_catalogo')
        cls.reponedor.groups.add(Group.objects.create(name=REPONEDOR))

    def setUp(self):
        self.client.force_login(self.administrador)
        self.lista = reverse('inventario:productos')
        self.registro = reverse('inventario:registrar_producto')

    def test_registro_valido_genera_identificador_y_confirma(self):
        respuesta = self.client.post(self.registro, {
            'nombre': '  Arroz   integral ', 'stock_minimo': '5',
        }, follow=True)
        producto = Producto.objects.get()
        self.assertIsNotNone(producto.pk)
        self.assertEqual((producto.nombre, producto.stock_minimo), ('Arroz integral', 5))
        self.assertContains(respuesta, 'Producto registrado correctamente.')
        self.assertContains(respuesta, 'Arroz integral')

    def test_nombre_obligatorio(self):
        for nombre in ('', '  \t  '):
            with self.subTest(nombre=nombre):
                respuesta = self.client.post(self.registro, {'nombre': nombre, 'stock_minimo': '5'})
                self.assertContains(respuesta, 'Indica el nombre del producto.')
                self.assertFalse(Producto.objects.exists())

    def test_rechaza_nombres_equivalentes_por_mayusculas_y_espacios(self):
        Producto.objects.create(nombre='Café molido', stock_minimo=3)
        respuesta = self.client.post(self.registro, {
            'nombre': '  CAFÉ\t molido  ', 'stock_minimo': '5',
        })
        self.assertContains(respuesta, 'Ya existe un producto con ese nombre.')
        self.assertEqual(Producto.objects.count(), 1)
        self.assertRedirects(self.client.post(self.registro, {
            'nombre': 'Cafe molido', 'stock_minimo': '5',
        }), self.lista)

    def test_stock_minimo_obligatorio_y_entero_positivo(self):
        for valor in ('', ' ', '0', '-3', '1.5', '3.0', 'abc', '1e2'):
            with self.subTest(valor=valor):
                respuesta = self.client.post(self.registro, {
                    'nombre': 'Arroz', 'stock_minimo': valor,
                })
                mensaje = ('El stock mínimo debe ser un número entero mayor que cero.'
                           if valor.strip() else 'Indica el stock mínimo.')
                self.assertContains(respuesta, mensaje)
                self.assertFalse(Producto.objects.exists())

    def test_edicion_conserva_id_y_permite_mantener_el_mismo_nombre(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        ruta = reverse('inventario:editar_producto', args=[producto.pk])
        self.assertContains(self.client.get(ruta), 'value="Arroz"')
        respuesta = self.client.post(ruta, {
            'nombre': 'ARROZ', 'stock_minimo': '6', 'id': '9999',
        }, follow=True)
        self.assertContains(respuesta, 'Cambios guardados correctamente.')
        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.stock_minimo), ('ARROZ', 6))
        self.assertEqual(Producto.objects.count(), 1)
        self.assertFalse(Producto.objects.filter(pk=9999).exists())

    def test_edicion_invalida_conserva_ambos_valores(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        Producto.objects.create(nombre='Fideos', stock_minimo=4)
        ruta = reverse('inventario:editar_producto', args=[producto.pk])
        for nombre, stock in ((' FIDEOS ', '8'), ('Maíz', '4.0'), (' ', '8'), ('Maíz', '')):
            with self.subTest(nombre=nombre, stock=stock):
                respuesta = self.client.post(ruta, {'nombre': nombre, 'stock_minimo': stock})
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context['formulario'].errors)
                producto.refresh_from_db()
                self.assertEqual((producto.nombre, producto.stock_minimo), ('Arroz', 3))

    def test_eliminacion_requiere_confirmacion_y_permite_cancelar(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        otro = Producto.objects.create(nombre='Sal', stock_minimo=1)
        ruta = reverse('inventario:eliminar_producto', args=[producto.pk])
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Confirmar eliminación')
        self.assertContains(respuesta, f'href="{self.lista}">Cancelar')
        self.assertEqual(self.client.get(self.lista).status_code, 200)
        self.assertEqual(self.client.post(ruta, {}).status_code, 200)
        self.assertTrue(Producto.objects.filter(pk=producto.pk).exists())
        respuesta = self.client.post(ruta, {'confirmar': 'si'}, follow=True)
        self.assertContains(respuesta, 'Producto eliminado correctamente.')
        self.assertEqual(list(Producto.objects.values_list('pk', flat=True)), [otro.pk])

    def test_relacion_protegida_simulada_bloquea_eliminacion(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        ruta = reverse('inventario:eliminar_producto', args=[producto.pk])
        with patch.object(Producto, 'delete', side_effect=ProtectedError('Protegido', [])):
            respuesta = self.client.post(ruta, {'confirmar': 'si'}, follow=True)
        self.assertContains(respuesta, 'tiene historial de inventario')
        self.assertTrue(Producto.objects.filter(pk=producto.pk).exists())

    def test_permisos_por_url_y_enlace_de_inicio(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        editar = reverse('inventario:editar_producto', args=[producto.pk])
        eliminar = reverse('inventario:eliminar_producto', args=[producto.pk])
        self.assertContains(self.client.get('/'), 'Gestionar productos')
        self.client.force_login(self.reponedor)
        self.assertNotContains(self.client.get('/'), 'Gestionar productos')
        for ruta in (self.lista, self.registro, editar, eliminar):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 403)
                self.assertEqual(self.client.post(ruta, {
                    'nombre': 'Otro', 'stock_minimo': '8', 'confirmar': 'si',
                }).status_code, 403)
                self.assertEqual(Client().get(ruta).status_code, 302)
        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.stock_minimo), ('Arroz', 3))
        self.assertEqual(Producto.objects.count(), 1)

    def test_csrf_obligatorio_en_altas_ediciones_y_eliminaciones(self):
        producto = Producto.objects.create(nombre='Arroz', stock_minimo=3)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.administrador)
        rutas = (self.registro, reverse('inventario:editar_producto', args=[producto.pk]),
                 reverse('inventario:eliminar_producto', args=[producto.pk]))
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.post(ruta, {
                    'nombre': 'Otro', 'stock_minimo': '8', 'confirmar': 'si',
                }).status_code, 403)
        producto.refresh_from_db()
        self.assertEqual((producto.nombre, producto.stock_minimo), ('Arroz', 3))
        self.assertEqual(Producto.objects.count(), 1)

    def test_base_de_datos_impide_duplicados_y_minimo_cero(self):
        producto = Producto.objects.create(nombre='Arroz integral', stock_minimo=3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Producto.objects.create(nombre=' ARROZ   integral ', stock_minimo=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Producto.objects.filter(pk=producto.pk).update(stock_minimo=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Producto.objects.create(nombre='   ', stock_minimo=5)
        producto.refresh_from_db()
        self.assertEqual(producto.stock_minimo, 3)
        self.assertEqual(Producto.objects.count(), 1)
