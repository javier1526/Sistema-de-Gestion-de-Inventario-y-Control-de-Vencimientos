from django.urls import path

from . import views


app_name = 'inventario'

urlpatterns = [
    path('', views.listar_productos, name='productos'),
    path('registrar/', views.guardar_producto, name='registrar_producto'),
    path('ingresos/registrar/', views.ingresar_lote, name='ingresar_lote'),
    path('<int:producto_id>/editar/', views.guardar_producto, name='editar_producto'),
    path('<int:producto_id>/eliminar/', views.eliminar_producto, name='eliminar_producto'),
]
