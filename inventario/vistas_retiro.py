from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from usuarios.permisos import requiere_permiso

from .forms import FormularioRetiro
from .models import Lote
from .servicios import registrar_retiro, validar_lote_para_retiro


@never_cache
@requiere_permiso('registrar_retiros')
@require_http_methods(['GET', 'POST'])
def retirar_lote(request, producto_id, lote_id):
    lote = get_object_or_404(
        Lote.objects.select_related('producto'), pk=lote_id, producto_id=producto_id,
    )
    termino = request.GET.get('q', '').strip()
    volver = reverse(
        'consulta_inventario:producto', args=[producto_id],
        query={'q': termino} if termino else None,
    )
    formulario = FormularioRetiro(request.POST if request.method == 'POST' else None)
    if formulario.is_valid():
        try:
            registrar_retiro(
                producto_id=producto_id, lote_id=lote_id,
                cantidad=formulario.cleaned_data['cantidad'], responsable=request.user,
            )
        except ValidationError as error:
            formulario.add_error('cantidad', error)
            lote.refresh_from_db(fields=['cantidad_restante', 'fecha_vencimiento'])
        except DatabaseError:
            formulario.add_error(None, 'No se pudo registrar el retiro. Intenta nuevamente.')
        else:
            messages.success(request, 'El retiro se registró correctamente.')
            return redirect(volver)

    motivo = None
    try:
        validar_lote_para_retiro(lote, 1)
    except ValidationError as error:
        motivo = error.messages[0]

    return render(request, 'inventario/formulario_retiro.html', {
        'lote': lote, 'formulario': formulario, 'volver': volver, 'motivo': motivo,
    })
