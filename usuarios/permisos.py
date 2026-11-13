from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


ADMINISTRADOR = 'Administrador'
REPONEDOR = 'Reponedor'

PERMISOS_POR_PERFIL = {
    ADMINISTRADOR: frozenset({
        'consultar_inventario', 'gestionar_productos', 'registrar_ingresos',
        'consultar_alertas', 'consultar_analisis', 'consultar_historial',
    }),
    REPONEDOR: frozenset({'consultar_inventario', 'registrar_retiros'}),
}


def obtener_perfil(usuario):
    """Obtiene el perfil operativo único de una cuenta activa y autenticada.

    Devuelve None si no se cumplen esas condiciones.
    """
    if not usuario.is_authenticated or not usuario.is_active:
        return None
    perfiles = list(usuario.groups.filter(
        name__in=PERMISOS_POR_PERFIL
    ).values_list('name', flat=True))
    # Ambos perfiles a la vez constituyen una configuración sin privilegios.
    return perfiles[0] if len(perfiles) == 1 else None


def tiene_permiso(usuario, accion):
    perfil = obtener_perfil(usuario)
    return accion in PERMISOS_POR_PERFIL.get(perfil, frozenset())


def requiere_permiso(accion):
    """Crea un decorador que exige sesión y permiso para la acción indicada."""
    def decorar(vista):
        @login_required
        @wraps(vista)
        def comprobar_permiso(request, *args, **kwargs):
            if not tiene_permiso(request.user, accion):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return comprobar_permiso
    return decorar

