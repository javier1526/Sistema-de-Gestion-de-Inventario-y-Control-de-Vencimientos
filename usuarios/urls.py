from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import IniciarSesionView, inicio

app_name = 'usuarios'

urlpatterns = [
    path('', inicio, name='inicio'),
    path(
        'acceso/iniciar-sesion/', IniciarSesionView.as_view(),
        name='iniciar_sesion',
    ),
    path('acceso/cerrar-sesion/', LogoutView.as_view(), name='cerrar_sesion'),
]

