import importlib
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class PruebasConfiguracion(SimpleTestCase):
    def test_configuracion_principal_usa_mysql_y_fecha_chilena(self):
        configuracion = importlib.import_module(
            'sistema_inventario_bodega.settings'
        )
        self.assertEqual(
            configuracion.DATABASES['default']['ENGINE'],
            'django.db.backends.mysql',
        )
        self.assertEqual(configuracion.LANGUAGE_CODE, 'es-cl')
        self.assertEqual(configuracion.TIME_ZONE, 'America/Santiago')
        self.assertTrue(configuracion.USE_TZ)

    @patch('usuarios.management.commands.verificar_base.connection')
    def test_verificacion_rechaza_base_distinta_sin_conectar(self, conexion):
        configuracion = {'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'otra_base', 'USER': 'usuario_ficticio',
        }}
        with patch(
            'usuarios.management.commands.verificar_base.settings'
        ) as ajustes:
            ajustes.DATABASES = configuracion
            with self.assertRaisesMessage(CommandError, 'no coincide'):
                call_command(
                    'verificar_base', base_esperada='inventario_bodega',
                )
        conexion.cursor.assert_not_called()

    @patch('usuarios.management.commands.verificar_base.connection')
    def test_verificacion_solo_consulta_y_reporta_tablas(self, conexion):
        configuracion = {'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'inventario_bodega', 'USER': 'usuario_ficticio',
        }}
        cursor = conexion.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('inventario_bodega', '8.4.0', 'InnoDB')
        cursor.fetchall.return_value = [('tabla_preexistente', 'InnoDB')]
        salida = StringIO()
        with patch(
            'usuarios.management.commands.verificar_base.settings'
        ) as ajustes:
            ajustes.DATABASES = configuracion
            call_command(
                'verificar_base', base_esperada='inventario_bodega',
                stdout=salida,
            )
        self.assertIn('Tablas existentes: 1', salida.getvalue())
        self.assertEqual(cursor.execute.call_count, 2)
        for llamada in cursor.execute.call_args_list:
            self.assertTrue(llamada.args[0].startswith('SELECT '))

