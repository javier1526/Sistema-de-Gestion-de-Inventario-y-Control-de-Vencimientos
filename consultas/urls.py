from django.urls import path

from . import views


app_name = 'consultas'

urlpatterns = [
    path('alertas/', views.consultar_alertas, name='alertas'),
    path('historial/', views.consultar_historial, name='historial'),
    path('vencimientos/', views.consultar_vencimientos, name='vencimientos'),
]
