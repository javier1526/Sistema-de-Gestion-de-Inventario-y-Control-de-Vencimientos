from django.db import DatabaseError
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from usuarios.permisos import requiere_permiso, tiene_permiso

from .lecturas import buscar_productos, consultar_lotes
from .models import Producto


def consulta_no_disponible(request):
    return render(request, 'inventario/error_consulta.html', {
        'mensaje': 'No se pudo completar la consulta. Intenta nuevamente.',
    }, status=503)


@never_cache
@requiere_permiso('consultar_inventario')
@require_safe
def buscar_inventario(request):
    termino = request.GET.get('q', '').strip()
    try:
        productos = list(buscar_productos(termino, timezone.localdate()))
    except DatabaseError:
        return consulta_no_disponible(request)
    return render(request, 'inventario/buscar_inventario.html', {
        'termino': termino, 'productos': productos,
    })


@never_cache
@requiere_permiso('consultar_inventario')
@require_safe
def consultar_producto(request, producto_id=None, *, agotados=False):
    termino = request.GET.get('q', '').strip()
    hoy = timezone.localdate()
    try:
        producto = Producto.objects.con_existencias(hoy).filter(pk=producto_id).first()
        if producto is None:
            return render(request, 'inventario/error_consulta.html', {
                'mensaje': 'Selecciona un producto válido para consultar sus lotes.',
                'termino': termino,
            }, status=404)
        lotes = consultar_lotes(producto, hoy, agotados=agotados)
    except DatabaseError:
        return consulta_no_disponible(request)

    contexto = {'producto': producto, 'termino': termino}
    if agotados:
        return render(request, 'inventario/lotes_agotados.html', {
            **contexto, 'lotes': lotes,
        })

    return render(request, 'inventario/consultar_producto.html', {
        **contexto,
        'lotes_vigentes': [lote for lote in lotes if not lote.vencido_en_consulta],
        'lotes_vencidos': [lote for lote in lotes if lote.vencido_en_consulta],
        'puede_retirar': tiene_permiso(request.user, 'registrar_retiros'),
    })
