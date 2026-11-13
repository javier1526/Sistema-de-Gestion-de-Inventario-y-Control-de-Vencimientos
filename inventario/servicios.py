from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from usuarios.permisos import tiene_permiso

from .models import Lote, Movimiento, Producto


MENSAJE_CODIGO_REPETIDO = 'Ya existe un lote con ese código para este producto.'
MENSAJE_CANTIDAD_RETIRO = 'La cantidad debe ser un número entero mayor que cero.'


def validar_vencimiento_ingreso(fecha_vencimiento):
    if fecha_vencimiento < timezone.localdate():
        raise ValidationError('La fecha de vencimiento no puede ser anterior a hoy.')


def registrar_ingreso(lote, responsable):
    """Persiste un lote nuevo validado y su movimiento en la misma transacción."""
    if not tiene_permiso(responsable, 'registrar_ingresos'):
        raise PermissionDenied

    try:
        with transaction.atomic():
            # El bloqueo coordina el ingreso con otros ingresos y con el borrado del producto.
            existe = Producto.objects.select_for_update().filter(pk=lote.producto_id).exists()
            if not existe:
                raise ValidationError({'producto': 'El producto seleccionado ya no existe.'})
            try:
                validar_vencimiento_ingreso(lote.fecha_vencimiento)
            except ValidationError as error:
                raise ValidationError({'fecha_vencimiento': error}) from error
            if lote.codigo_ya_registrado():
                raise ValidationError({'codigo_lote': MENSAJE_CODIGO_REPETIDO})

            lote.cantidad_restante = lote.cantidad_ingresada
            lote.save(force_insert=True)
            return Movimiento.objects.create(
                lote=lote, responsable=responsable, tipo=Movimiento.Tipo.INGRESO,
                cantidad=lote.cantidad_ingresada,
            )
    except IntegrityError as error:
        if lote.codigo_ya_registrado():
            raise ValidationError({'codigo_lote': MENSAJE_CODIGO_REPETIDO}) from error
        raise


def validar_lote_para_retiro(lote, cantidad):
    """Rechaza lotes vencidos o cantidades superiores a su saldo restante."""
    if lote.esta_vencido():
        raise ValidationError('El lote está vencido.')
    if cantidad > lote.cantidad_restante:
        raise ValidationError(
            'Solo hay %(saldo)s unidades disponibles en este lote.',
            code='saldo_insuficiente', params={'saldo': lote.cantidad_restante},
        )


def registrar_retiro(*, producto_id, lote_id, cantidad, responsable):
    """Registra un retiro del Reponedor y su movimiento de forma atómica.

    Bloquea el lote y revalida su saldo y vencimiento antes del descuento.
    """
    if not tiene_permiso(responsable, 'registrar_retiros'):
        raise PermissionDenied
    if type(cantidad) is not int or cantidad < 1:
        raise ValidationError(MENSAJE_CANTIDAD_RETIRO)

    with transaction.atomic():
        try:
            lote = Lote.objects.select_for_update().get(
                pk=lote_id, producto_id=producto_id,
            )
        except Lote.DoesNotExist as error:
            raise ValidationError('El lote no pertenece al producto seleccionado.') from error

        validar_lote_para_retiro(lote, cantidad)
        lote.cantidad_restante -= cantidad
        lote.save(update_fields=['cantidad_restante'])
        return Movimiento.objects.create(
            lote=lote, responsable=responsable, tipo=Movimiento.Tipo.RETIRO,
            cantidad=cantidad,
        )
