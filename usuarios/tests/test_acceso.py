from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, identify_hasher
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from usuarios.permisos import (
    ADMINISTRADOR, PERMISOS_POR_PERFIL, REPONEDOR,
    obtener_perfil, tiene_permiso,
)


@override_settings(ROOT_URLCONF='usuarios.tests.urls')
class PruebasAcceso(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clave = 'Clave-ficticia-de-prueba-482!'
        cls.grupo_administrador = Group.objects.create(name=ADMINISTRADOR)
        cls.grupo_reponedor = Group.objects.create(name=REPONEDOR)
        modelo_usuario = get_user_model()
        cls.administrador = modelo_usuario.objects.create_user(
            'administrador', password=cls.clave,
        )
        cls.administrador.groups.add(cls.grupo_administrador)
        cls.reponedor = modelo_usuario.objects.create_user(
            'reponedor', password=cls.clave,
        )
        cls.reponedor.groups.add(cls.grupo_reponedor)
        cls.sin_perfil = modelo_usuario.objects.create_user(
            'sin_perfil', password=cls.clave,
        )
        cls.ambiguo = modelo_usuario.objects.create_user(
            'ambiguo', password=cls.clave,
        )
        cls.ambiguo.groups.add(cls.grupo_administrador, cls.grupo_reponedor)
        cls.inactivo = modelo_usuario.objects.create_user(
            'inactivo', password=cls.clave, is_active=False,
        )
        cls.inactivo.groups.add(cls.grupo_reponedor)

    def iniciar_sesion(self, usuario, clave=None, **datos):
        return self.client.post(reverse('usuarios:iniciar_sesion'), {
            'username': usuario.username,
            'password': clave or self.clave, **datos,
        })

    def test_credenciales_validas_para_ambos_perfiles(self):
        for usuario, perfil in [
            (self.administrador, ADMINISTRADOR), (self.reponedor, REPONEDOR),
        ]:
            with self.subTest(perfil=perfil):
                respuesta = self.iniciar_sesion(usuario)
                self.assertRedirects(respuesta, reverse('usuarios:inicio'))
                self.assertEqual(
                    self.client.session['_auth_user_id'], str(usuario.pk),
                )
                inicio = self.client.get(reverse('usuarios:inicio'))
                self.assertContains(inicio, perfil)
                self.assertContains(inicio, usuario.username)
                self.assertEqual(inicio.context['perfil'], perfil)
                self.client.logout()

    def test_credenciales_incorrectas_no_crean_sesion(self):
        respuesta = self.iniciar_sesion(self.administrador, 'incorrecta')
        self.assertContains(
            respuesta, 'El usuario o la contraseña no son válidos.',
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_usuario_inexistente_recibe_mensaje_generico(self):
        respuesta = self.client.post(reverse('usuarios:iniciar_sesion'), {
            'username': 'no_existe', 'password': self.clave,
        })
        self.assertContains(
            respuesta, 'El usuario o la contraseña no son válidos.',
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cuenta_inactiva_no_inicia_sesion(self):
        respuesta = self.iniciar_sesion(self.inactivo)
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cuentas_sin_perfil_unico_no_inician_sesion(self):
        for usuario in [self.sin_perfil, self.ambiguo]:
            with self.subTest(usuario=usuario.username):
                respuesta = self.iniciar_sesion(usuario)
                self.assertContains(
                    respuesta, 'Tu cuenta no tiene un perfil válido.',
                )
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_campos_obligatorios_y_etiquetas(self):
        respuesta = self.client.post(reverse('usuarios:iniciar_sesion'), {})
        self.assertContains(respuesta, 'El campo usuario es obligatorio.')
        self.assertContains(respuesta, 'El campo contraseña es obligatorio.')
        self.assertContains(respuesta, 'for="id_username"')
        self.assertContains(respuesta, 'for="id_password"')
        self.assertContains(respuesta, 'type="password"')
        self.assertContains(respuesta, 'name="csrfmiddlewaretoken"')
        self.assertContains(respuesta, 'name="viewport"')
        self.assertContains(respuesta, 'Saltar al contenido')

    def test_clave_protegida_con_mecanismo_django(self):
        usuario = get_user_model().objects.get(pk=self.administrador.pk)
        valor_guardado = usuario.password
        self.assertNotEqual(valor_guardado, self.clave)
        self.assertTrue(check_password(self.clave, valor_guardado))
        self.assertIsNotNone(identify_hasher(valor_guardado))

    def test_anonimo_no_accede_a_rutas_protegidas(self):
        for ruta in ['/', '/prueba/administrador/', '/prueba/reponedor/']:
            with self.subTest(ruta=ruta):
                respuesta = self.client.get(ruta)
                acceso = reverse('usuarios:iniciar_sesion')
                self.assertRedirects(
                    respuesta, f'{acceso}?next={ruta}',
                    fetch_redirect_response=False,
                )

    def test_permisos_por_url_se_aplican_en_el_servidor(self):
        casos = [
            (self.administrador, '/prueba/administrador/', 200),
            (self.administrador, '/prueba/reponedor/', 403),
            (self.reponedor, '/prueba/administrador/', 403),
            (self.reponedor, '/prueba/reponedor/', 200),
        ]
        for usuario, ruta, estado in casos:
            with self.subTest(usuario=usuario.username, ruta=ruta):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(ruta).status_code, estado)

    def test_matriz_completa_de_permisos_y_accion_desconocida(self):
        acciones = set().union(*PERMISOS_POR_PERFIL.values())
        acciones.add('accion_inexistente')
        for usuario, perfil in [
            (self.administrador, ADMINISTRADOR), (self.reponedor, REPONEDOR),
        ]:
            for accion in acciones:
                with self.subTest(perfil=perfil, accion=accion):
                    self.assertEqual(
                        tiene_permiso(usuario, accion),
                        accion in PERMISOS_POR_PERFIL[perfil],
                    )

    def test_superusuario_no_omite_restricciones_del_perfil(self):
        self.administrador.is_superuser = True
        self.administrador.is_staff = True
        self.administrador.save()
        self.client.force_login(self.administrador)
        respuesta = self.client.get('/prueba/reponedor/')
        self.assertEqual(respuesta.status_code, 403)

    def test_cambio_de_perfil_se_revalida_en_cada_solicitud(self):
        self.client.force_login(self.administrador)
        self.administrador.groups.clear()
        self.assertEqual(self.client.get('/').status_code, 403)
        self.assertIsNone(obtener_perfil(self.administrador))

    def test_cierre_de_sesion_post_invalida_acceso(self):
        self.iniciar_sesion(self.reponedor)
        respuesta = self.client.post(reverse('usuarios:cerrar_sesion'))
        self.assertRedirects(respuesta, reverse('usuarios:iniciar_sesion'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_cierre_por_get_no_cierra_la_sesion(self):
        self.iniciar_sesion(self.reponedor)
        respuesta = self.client.get(reverse('usuarios:cerrar_sesion'))
        self.assertEqual(respuesta.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_y_logout_exigen_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        ruta_login = reverse('usuarios:iniciar_sesion')
        self.assertEqual(cliente.post(ruta_login, {}).status_code, 403)
        cliente.get(ruta_login)
        token = cliente.cookies['csrftoken'].value
        respuesta = cliente.post(ruta_login, {
            'username': self.reponedor.username, 'password': self.clave,
            'csrfmiddlewaretoken': token,
        })
        self.assertEqual(respuesta.status_code, 302)
        respuesta = cliente.post(reverse('usuarios:cerrar_sesion'))
        self.assertEqual(respuesta.status_code, 403)
        cliente.get('/')
        token = cliente.cookies['csrftoken'].value
        self.assertEqual(cliente.post(reverse('usuarios:cerrar_sesion'), {
            'csrfmiddlewaretoken': token,
        }).status_code, 302)
        self.assertNotIn('_auth_user_id', cliente.session)

    def test_next_no_redirige_a_sitio_externo(self):
        respuesta = self.iniciar_sesion(
            self.reponedor, next='https://example.com/',
        )
        self.assertRedirects(respuesta, reverse('usuarios:inicio'))

    def test_inicio_no_se_almacena_en_cache(self):
        self.iniciar_sesion(self.reponedor)
        self.assertIn('no-store', self.client.get('/')['Cache-Control'])

    def test_preparar_perfiles_es_idempotente_y_no_modifica_cuentas(self):
        salida = StringIO()
        call_command('preparar_perfiles', stdout=salida)
        call_command('preparar_perfiles', stdout=salida)
        self.assertEqual(
            Group.objects.filter(name__in=PERMISOS_POR_PERFIL).count(), 2,
        )
        self.assertEqual(obtener_perfil(self.reponedor), REPONEDOR)

    @patch('usuarios.management.commands.configurar_usuario.getpass')
    def test_preconfiguracion_sin_privilegios_tecnicos(self, solicitar_clave):
        solicitar_clave.side_effect = [self.clave, self.clave]
        call_command(
            'configurar_usuario', usuario='trabajador_nuevo',
            perfil=REPONEDOR, stdout=StringIO(),
        )
        usuario = get_user_model().objects.get(username='trabajador_nuevo')
        self.assertTrue(usuario.check_password(self.clave))
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(obtener_perfil(usuario), REPONEDOR)

    def test_preconfiguracion_no_sobrescribe_cuenta_existente(self):
        with self.assertRaisesMessage(CommandError, 'El usuario ya existe'):
            call_command(
                'configurar_usuario', usuario='administrador',
                perfil=REPONEDOR,
            )
        self.assertEqual(obtener_perfil(self.administrador), ADMINISTRADOR)

    @patch('usuarios.management.commands.configurar_usuario.getpass')
    def test_rechaza_clave_debil_sin_crear_cuenta(self, solicitar_clave):
        solicitar_clave.side_effect = ['123', '123']
        with self.assertRaises(CommandError):
            call_command(
                'configurar_usuario', usuario='cuenta_invalida',
                perfil=REPONEDOR,
            )
        cuentas = get_user_model().objects.filter(username='cuenta_invalida')
        self.assertFalse(cuentas.exists())

    def test_rutas_de_etapas_posteriores_no_estan_publicadas(self):
        for ruta in [
            '/inventario/retiros/', '/retiros/',
            '/consultas/',
        ]:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 404)

