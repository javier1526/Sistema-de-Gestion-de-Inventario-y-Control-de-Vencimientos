from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from usuarios.permisos import requiere_permiso

from .lecturas import alertas_stock, analizar_vencimientos, historial_movimientos


def mostrar_consulta(request, plantilla, obtener_contexto):
    try:
        contexto = obtener_contexto()
    except DatabaseError:
        return render(request, 'consultas/error.html', status=503)
    return render(request, plantilla, contexto)


@never_cache
@requiere_permiso('consultar_alertas')
@require_safe
def consultar_alertas(request):
    return mostrar_consulta(request, 'consultas/alertas.html', alertas_stock)


@never_cache
@requiere_permiso('consultar_historial')
@require_safe
def consultar_historial(request):
    return mostrar_consulta(request, 'consultas/historial.html', historial_movimientos)


@never_cache
@requiere_permiso('consultar_analisis')
@require_safe
def consultar_vencimientos(request):
    return mostrar_consulta(request, 'consultas/vencimientos.html', analizar_vencimientos)
