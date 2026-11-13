from django.urls import path

from . import vistas_consulta
from .vistas_retiro import retirar_lote


app_name = 'consulta_inventario'

urlpatterns = [
    path('', vistas_consulta.buscar_inventario, name='buscar'),
    path('<int:producto_id>/', vistas_consulta.consultar_producto, name='producto'),
    path(
        '<int:producto_id>/agotados/', vistas_consulta.consultar_producto,
        {'agotados': True}, name='agotados',
    ),
    path('agotados/', vistas_consulta.consultar_producto, {'agotados': True}),
    path('<int:producto_id>/lotes/<int:lote_id>/retirar/', retirar_lote, name='retirar'),
]
