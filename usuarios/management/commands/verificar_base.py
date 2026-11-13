from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Inspecciona la base prevista sin modificar datos ni migrar.'
    # Comprobar el destino antes de cualquier chequeo que abra una conexión.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--base-esperada', required=True)

    def handle(self, *args, **options):
        configuracion = settings.DATABASES['default']
        if configuracion['ENGINE'] != 'django.db.backends.mysql':
            raise CommandError('Esta verificación requiere el backend MySQL.')
        if (
            not configuracion['NAME']
            or configuracion['NAME'] != options['base_esperada']
        ):
            raise CommandError(
                'La base configurada no coincide con la base prevista.'
            )
        if not configuracion['USER']:
            raise CommandError('Debes configurar MYSQL_USER.')
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT DATABASE(), VERSION(), @@default_storage_engine'
                )
                nombre_base, version, motor = cursor.fetchone()
                if nombre_base != options['base_esperada']:
                    raise CommandError(
                        'El servidor conectó con una base '
                        'distinta de la prevista.'
                    )
                cursor.execute(
                    'SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES '
                    'WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME'
                )
                tablas = cursor.fetchall()
        except CommandError:
            raise
        except Exception as error:
            # Los mensajes del conector podrían incluir información sensible.
            raise CommandError(
                'No se pudo verificar la conexión. Revisa motor, versión, '
                'servicio y variables locales.'
            ) from error
        self.stdout.write(
            f'Base confirmada: {nombre_base}. '
            f'Versión: {version}. Motor: {motor}.'
        )
        self.stdout.write(f'Tablas existentes: {len(tablas)}.')
        for nombre, motor_tabla in tablas:
            self.stdout.write(f'  {nombre}: {motor_tabla}')
        self.stdout.write(
            'No se ejecutaron migraciones ni se modificaron datos.'
        )

