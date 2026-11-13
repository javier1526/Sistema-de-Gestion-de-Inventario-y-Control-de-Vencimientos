from .models import Producto


def buscar_productos(termino, hoy):
    """Busca nombres por coincidencia parcial y añade sus existencias.

    Ignora mayúsculas y espacios externos; sin término no hay resultados.
    """
    termino = termino.strip().casefold()
    if not termino:
        return Producto.objects.none()

    # La comparación Unicode es igual en SQLite y MySQL, sin depender de su intercalación.
    nombres = Producto.objects.order_by().values_list('pk', 'nombre').iterator()
    coincidencias = [pk for pk, nombre in nombres if termino in nombre.casefold()]
    return Producto.objects.filter(pk__in=coincidencias).con_existencias(hoy)


def consultar_lotes(producto, hoy, *, agotados=False):
    """Lista lotes con saldo o agotados, ordenados por vencimiento.

    Añade su estado de vencimiento sin modificar la base de datos.
    """
    lotes = producto.lotes.filter(cantidad_restante=0) if agotados else (
        producto.lotes.filter(cantidad_restante__gt=0)
    )
    lotes = list(lotes.order_by('fecha_vencimiento', 'pk'))
    for lote in lotes:
        lote.vencido_en_consulta = lote.esta_vencido(hoy)
    return lotes
