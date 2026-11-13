from django.contrib.auth.views import LoginView
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from .forms import FormularioInicioSesion
from .permisos import obtener_perfil, requiere_permiso


class IniciarSesionView(LoginView):
    template_name = 'usuarios/iniciar_sesion.html'
    authentication_form = FormularioInicioSesion
    redirect_authenticated_user = True


@never_cache
@requiere_permiso('consultar_inventario')
def inicio(request):
    return render(request, 'usuarios/inicio.html', {
        'perfil': obtener_perfil(request.user),
    })

