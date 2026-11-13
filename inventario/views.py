from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from usuarios.permisos import requiere_permiso

from .forms import FormularioIngreso, FormularioProducto, MENSAJE_NOMBRE_DUPLICADO
from .models import Producto
from .servicios import registrar_ingreso


@never_cache
@requiere_permiso('gestionar_productos')
@require_safe
def listar_productos(request):
    return render(request, 'inventario/productos.html', {
        'productos': Producto.objects.all(),
    })


@never_cache
@requiere_permiso('gestionar_productos')
@require_http_methods(['GET', 'POST'])
def guardar_producto(request, producto_id=None):
    if request.method == 'POST':
        formulario = None
        try:
            with transaction.atomic():
                producto = (
                    get_object_or_404(Producto.objects.select_for_update(), pk=producto_id)
                    if producto_id is not None else None
                )
                formulario = FormularioProducto(request.POST, instance=producto)
                if formulario.is_valid():
                    if producto is None:
                        formulario.save()
                        aviso = 'Producto registrado correctamente.'
                    else:
                        if formulario.changed_data:
                            producto.save(update_fields=formulario.changed_data)
                        aviso = 'Cambios guardados correctamente.'
                    messages.success(request, aviso)
                    return redirect('inventario:productos')
        except IntegrityError:
            # Otro registro puede ganar la carrera después de validar el nombre.
            if formulario is None:
                raise
            nombre = formulario.cleaned_data.get('nombre')
            if not nombre or not formulario.nombre_duplicado(nombre):
                raise
            formulario.add_error('nombre', MENSAJE_NOMBRE_DUPLICADO)
    else:
        producto = (
            get_object_or_404(Producto, pk=producto_id)
            if producto_id is not None else None
        )
        formulario = FormularioProducto(instance=producto)

    return render(request, 'inventario/formulario_producto.html', {
        'formulario': formulario,
        'editando': producto_id is not None,
    })


@never_cache
@requiere_permiso('gestionar_productos')
@require_http_methods(['GET', 'POST'])
def eliminar_producto(request, producto_id):
    if request.method == 'POST' and request.POST.get('confirmar') == 'si':
        try:
            with transaction.atomic():
                producto = get_object_or_404(
                    Producto.objects.select_for_update(), pk=producto_id,
                )
                producto.delete()
        except (ProtectedError, RestrictedError):
            messages.error(
                request, 'El producto no se puede eliminar porque tiene historial de inventario.',
            )
        else:
            messages.success(request, 'Producto eliminado correctamente.')
        return redirect('inventario:productos')

    return render(request, 'inventario/confirmar_eliminacion.html', {
        'producto': get_object_or_404(Producto, pk=producto_id),
    })


@never_cache
@requiere_permiso('registrar_ingresos')
@require_http_methods(['GET', 'POST'])
def ingresar_lote(request):
    formulario = FormularioIngreso(request.POST if request.method == 'POST' else None)
    if formulario.is_valid():
        try:
            registrar_ingreso(formulario.save(commit=False), request.user)
        except ValidationError as error:
            formulario.add_error(None, error)
        except DatabaseError:
            formulario.add_error(None, 'No se pudo registrar el ingreso. Intenta nuevamente.')
        else:
            messages.success(request, 'El lote y su ingreso se registraron correctamente.')
            return redirect('inventario:ingresar_lote')

    return render(request, 'inventario/formulario_ingreso.html', {'formulario': formulario})
