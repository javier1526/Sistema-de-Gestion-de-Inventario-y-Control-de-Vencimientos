from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from usuarios.permisos import PERMISOS_POR_PERFIL


class Command(BaseCommand):
    help = 'Crea una cuenta individual nueva sin sobrescribir usuarios.'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', required=True)
        parser.add_argument(
            '--perfil', required=True, choices=PERMISOS_POR_PERFIL,
        )

    def handle(self, *args, **options):
        nombre_usuario = options['usuario'].strip()
        modelo_usuario = get_user_model()
        if modelo_usuario.objects.filter(username=nombre_usuario).exists():
            raise CommandError(
                'El usuario ya existe; no se modificó la cuenta.'
            )
        try:
            perfil = Group.objects.get(name=options['perfil'])
        except Group.DoesNotExist as error:
            raise CommandError(
                'Ejecuta preparar_perfiles antes de crear cuentas.'
            ) from error
        clave = getpass('Contraseña: ')
        confirmacion = getpass('Confirmar contraseña: ')
        if clave != confirmacion:
            raise CommandError('Las contraseñas no coinciden.')
        usuario = modelo_usuario(username=nombre_usuario)
        try:
            usuario.full_clean(exclude=['password'])
            validate_password(clave, user=usuario)
        except ValidationError as error:
            raise CommandError(' '.join(error.messages)) from error
        with transaction.atomic():
            usuario.set_password(clave)
            usuario.save()
            usuario.groups.add(perfil)
        self.stdout.write(self.style.SUCCESS(
            'Cuenta individual creada correctamente.'
        ))

