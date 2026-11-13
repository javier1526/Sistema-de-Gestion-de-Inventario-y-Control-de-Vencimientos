"""Rutas exclusivas de pruebas; no implementan funciones de inventario."""

from django.http import HttpResponse
from django.urls import include, path

from usuarios.permisos import requiere_permiso


@requiere_permiso('gestionar_productos')
def acceso_administrador(request):
    return HttpResponse('Acceso autorizado')


@requiere_permiso('registrar_retiros')
def acceso_reponedor(request):
    return HttpResponse('Acceso autorizado')


urlpatterns = [
    path('', include('sistema_inventario_bodega.urls')),
    path('prueba/administrador/', acceso_administrador),
    path('prueba/reponedor/', acceso_reponedor),
]

