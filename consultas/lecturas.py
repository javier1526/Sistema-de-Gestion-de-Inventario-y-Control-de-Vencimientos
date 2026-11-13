from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from inventario.models import Lote, Movimiento, Producto


INTERVALOS_VENCIMIENTO = ((0, 30), (31, 60), (61, 90))


def alertas_stock():
    """Obtiene productos con disponible igual o inferior al mínimo vigente."""
    productos = Producto.objects.con_existencias().filter(
        stock_disponible__lte=F('stock_minimo'),
    )
    return {'productos': list(productos)}


def historial_movimientos():
    movimientos = Movimiento.objects.select_related(
        'responsable', 'lote__producto',
    ).order_by('-fecha_hora', '-pk')
    return {'movimientos': list(movimientos)}


def analizar_vencimientos():
    """Agrupa lotes vigentes con saldo y valora su riesgo potencial en CLP.

    Calcula detalles, subtotales y total para 0–30, 31–60 y 61–90 días.
    """
    hoy = timezone.localdate()
    intervalos = [
        {'desde': desde, 'hasta': hasta, 'subtotal': 0, 'detalles': []}
        for desde, hasta in INTERVALOS_VENCIMIENTO
    ]
    lotes = Lote.objects.filter(
        cantidad_restante__gt=0,
        fecha_vencimiento__range=(hoy, hoy + timedelta(days=intervalos[-1]['hasta'])),
    ).select_related('producto').order_by('fecha_vencimiento', 'pk')

    for lote in lotes:
        dias = lote.dias_para_vencer(hoy)
        valor = lote.cantidad_restante * lote.costo_unitario_clp
        intervalo = next(banda for banda in intervalos if banda['desde'] <= dias <= banda['hasta'])
        intervalo['detalles'].append({'lote': lote, 'dias': dias, 'valor': valor})
        intervalo['subtotal'] += valor

    return {
        'intervalos': intervalos,
        'total': sum(intervalo['subtotal'] for intervalo in intervalos),
    }
