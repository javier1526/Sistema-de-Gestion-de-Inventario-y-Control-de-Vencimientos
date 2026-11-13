from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from usuarios.permisos import PERMISOS_POR_PERFIL


class Command(BaseCommand):
    help = 'Crea los dos grupos del sistema sin modificar cuentas existentes.'

    @transaction.atomic
    def handle(self, *args, **options):
        for nombre in PERMISOS_POR_PERFIL:
            _, creado = Group.objects.get_or_create(name=nombre)
            estado = 'creado' if creado else 'ya existente'
            self.stdout.write(f'Perfil {nombre}: {estado}.')

