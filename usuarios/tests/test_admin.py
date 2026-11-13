from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from inventario.models import Lote, Movimiento, Producto
from usuarios.permisos import ADMINISTRADOR, REPONEDOR, obtener_perfil


class PruebasAdministracionTecnica(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clave = 'Clave-ficticia-para-pruebas-974!'
        cls.usuarios = get_user_model()
        cls.tecnico = cls.usuarios.objects.create_superuser(
            'tecnico_prueba', password=cls.clave,
        )
        cls.administrador = cls.usuarios.objects.create_user(
            'administrador', password=cls.clave,
        )
        cls.reponedor = cls.usuarios.objects.create_user(
            'reponedor', password=cls.clave,
        )
        cls.grupo_administrador = Group.objects.create(name=ADMINISTRADOR)
        cls.grupo_reponedor = Group.objects.create(name=REPONEDOR)
        cls.administrador.groups.add(cls.grupo_administrador)
        cls.reponedor.groups.add(cls.grupo_reponedor)

    def crear_trabajador(self, nombre):
        self.client.force_login(self.tecnico)
        respuesta = self.client.post(reverse('admin:auth_user_add'), {
            'username': nombre, 'usable_password': 'true',
            'password1': self.clave, 'password2': self.clave, '_save': 'Guardar',
        })
        self.assertEqual(respuesta.status_code, 302)
        trabajador = self.usuarios.objects.get(username=nombre)
        self.assertTrue(trabajador.check_password(self.clave))
        return trabajador

    def configurar_trabajador(self, trabajador, grupos, activo=True):
        fecha = timezone.localtime(trabajador.date_joined)
        datos = {
            'username': trabajador.username,
            'first_name': '', 'last_name': '', 'email': '',
            'groups': [grupo.pk for grupo in grupos],
            'date_joined_0': fecha.strftime('%Y-%m-%d'),
            'date_joined_1': fecha.strftime('%H:%M:%S'),
            '_save': 'Guardar',
        }
        if activo:
            datos['is_active'] = 'on'
        respuesta = self.client.post(
            reverse('admin:auth_user_change', args=[trabajador.pk]), datos,
        )
        self.assertEqual(respuesta.status_code, 302)
        trabajador.refresh_from_db()

    def test_administracion_estandar_solo_de_cuentas_y_grupos(self):
        self.assertIsInstance(admin.site.get_model_admin(self.usuarios), UserAdmin)
        self.assertIsInstance(admin.site.get_model_admin(Group), GroupAdmin)
        for modelo in (Producto, Lote, Movimiento):
            self.assertFalse(admin.site.is_registered(modelo))
        self.assertEqual(Client().get(reverse('admin:login')).status_code, 200)
        respuesta = self.client.post(reverse('admin:login'), {
            'username': self.tecnico.username, 'password': self.clave,
            'next': reverse('admin:index'),
        })
        self.assertRedirects(respuesta, reverse('admin:index'))
        self.assertEqual(self.client.get(reverse('admin:auth_user_changelist')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:auth_group_changelist')).status_code, 200)
        self.assertIsNone(obtener_perfil(self.tecnico))
        self.assertEqual(self.client.get('/inventario/').status_code, 403)
        cliente = Client()
        respuesta = cliente.post(reverse('usuarios:iniciar_sesion'), {
            'username': self.tecnico.username, 'password': self.clave,
        })
        self.assertContains(respuesta, 'Tu cuenta no tiene un perfil válido.')

    def test_cuentas_operativas_no_acceden_a_admin(self):
        for usuario in (self.administrador, self.reponedor):
            with self.subTest(usuario=usuario.username):
                self.assertFalse(usuario.is_staff or usuario.is_superuser)
                self.client.force_login(usuario)
                respuesta = self.client.get(reverse('admin:index'))
                self.assertRedirects(
                    respuesta, '/admin/login/?next=/admin/', fetch_redirect_response=False,
                )
                self.client.logout()
                respuesta = self.client.post(reverse('admin:login'), {
                    'username': usuario.username, 'password': self.clave, 'next': '/admin/',
                })
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_alta_y_asignacion_por_panel_admiten_ambos_perfiles(self):
        for grupo in (self.grupo_administrador, self.grupo_reponedor):
            with self.subTest(grupo=grupo.name):
                trabajador = self.crear_trabajador('nuevo_' + str(grupo.pk))
                self.configurar_trabajador(trabajador, [grupo])
                self.assertTrue(trabajador.is_active)
                self.assertFalse(trabajador.is_staff or trabajador.is_superuser)
                self.assertEqual(obtener_perfil(trabajador), grupo.name)
                cliente = Client()
                self.assertEqual(cliente.post(reverse('usuarios:iniciar_sesion'), {
                    'username': trabajador.username, 'password': self.clave,
                }).status_code, 302)
                self.assertContains(cliente.get('/'), grupo.name)

    def test_cuentas_sin_grupo_con_doble_grupo_o_inactivas_se_rechazan(self):
        trabajador = self.crear_trabajador('nuevo_sin_perfil')
        for grupos, activo in (
            ([], True), ([self.grupo_administrador, self.grupo_reponedor], True),
            ([self.grupo_reponedor], False),
        ):
            with self.subTest(grupos=grupos, activo=activo):
                self.configurar_trabajador(trabajador, grupos, activo)
                cliente = Client()
                respuesta = cliente.post(reverse('usuarios:iniciar_sesion'), {
                    'username': trabajador.username, 'password': self.clave,
                })
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotIn('_auth_user_id', cliente.session)
                self.assertEqual(cliente.get('/inventario/').status_code, 302)

    def test_post_del_panel_exige_csrf_y_no_altera_inventario(self):
        producto = Producto.objects.create(nombre='Producto conservado', stock_minimo=2)
        antes = list(Producto.objects.values_list())
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.tecnico)
        respuesta = cliente.post(reverse('admin:auth_user_add'), {
            'username': 'csrf_ausente', 'password1': self.clave, 'password2': self.clave,
        })
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(self.usuarios.objects.filter(username='csrf_ausente').exists())
        self.assertEqual(list(Producto.objects.values_list()), antes)
        self.assertEqual(producto.stock_minimo, 2)
        self.assertEqual(Lote.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
