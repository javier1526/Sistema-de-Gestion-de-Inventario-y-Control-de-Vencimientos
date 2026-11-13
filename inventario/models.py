from hashlib import sha256

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def limpiar_nombre_producto(nombre):
    return ' '.join(nombre.split())


def clave_para_nombre(nombre):
    nombre_normalizado = limpiar_nombre_producto(nombre).casefold()
    return sha256(nombre_normalizado.encode('utf-8')).hexdigest()


class ProductosQuerySet(models.QuerySet):
    def con_existencias(self, hoy=None):
        """Anota el stock físico y el disponible de cada producto.

        El físico incluye vencidos; el disponible solo suma lotes vigentes.
        """
        hoy = hoy or timezone.localdate()
        return self.annotate(
            stock_fisico=models.Sum('lotes__cantidad_restante', default=0),
            stock_disponible=models.Sum(
                'lotes__cantidad_restante', default=0,
                filter=models.Q(lotes__fecha_vencimiento__gte=hoy),
            ),
        )


class Producto(models.Model):
    nombre = models.CharField('nombre', max_length=255)
    clave_nombre = models.CharField(max_length=64, unique=True, editable=False)
    stock_minimo = models.PositiveIntegerField(
        'stock mínimo', validators=[MinValueValidator(1)],
    )
    objects = ProductosQuerySet.as_manager()

    class Meta:
        ordering = ('nombre', 'pk')
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(nombre='') & ~models.Q(clave_nombre=''),
                name='producto_nombre_informado',
            ),
            models.CheckConstraint(
                condition=models.Q(stock_minimo__gt=0),
                name='producto_stock_minimo_positivo',
            ),
        ]

    def __str__(self):
        return self.nombre

    def calcular_stock_fisico(self):
        return Producto.objects.con_existencias().values_list(
            'stock_fisico', flat=True,
        ).get(pk=self.pk)

    def save(self, *, update_fields=None, **kwargs):
        if update_fields is None or 'nombre' in update_fields:
            self.nombre = limpiar_nombre_producto(self.nombre)
            # La clave evita que la intercalación de MySQL ignore diferencias de acentos.
            self.clave_nombre = clave_para_nombre(self.nombre)
            if update_fields is not None:
                update_fields = {*update_fields, 'clave_nombre'}
        super().save(update_fields=update_fields, **kwargs)


class Lote(models.Model):
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name='lotes',
    )
    codigo_lote = models.CharField('código de lote', max_length=100)
    clave_codigo = models.CharField(max_length=64, editable=False)
    fecha_vencimiento = models.DateField('fecha de vencimiento')
    cantidad_ingresada = models.PositiveIntegerField(
        'cantidad ingresada', validators=[MinValueValidator(1)],
    )
    cantidad_restante = models.PositiveIntegerField('cantidad restante')
    costo_unitario_clp = models.PositiveIntegerField(
        'costo unitario de adquisición en CLP', validators=[MinValueValidator(1)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('producto', 'clave_codigo'), name='lote_codigo_por_producto',
            ),
            models.CheckConstraint(
                condition=~models.Q(codigo_lote='') & ~models.Q(clave_codigo=''),
                name='lote_codigo_informado',
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad_ingresada__gt=0, costo_unitario_clp__gt=0),
                name='lote_ingreso_y_costo_positivos',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cantidad_restante__gte=0,
                    cantidad_restante__lte=models.F('cantidad_ingresada'),
                ),
                name='lote_saldo_en_rango',
            ),
        ]

    def __str__(self):
        return self.codigo_lote

    def esta_vencido(self, hoy=None):
        """Considera vencido el lote desde el día posterior a su vencimiento."""
        return self.dias_para_vencer(hoy) < 0

    def dias_para_vencer(self, hoy=None):
        return (self.fecha_vencimiento - (hoy or timezone.localdate())).days

    def codigo_ya_registrado(self):
        return Lote.objects.filter(
            producto_id=self.producto_id, clave_codigo=self._clave_para_codigo(),
        ).exists()

    def _clave_para_codigo(self):
        # La intercalación de MySQL no debe equiparar acentos ni espacios internos.
        return sha256(self.codigo_lote.strip().casefold().encode('utf-8')).hexdigest()

    def save(self, *, update_fields=None, **kwargs):
        if update_fields is None or 'codigo_lote' in update_fields:
            self.codigo_lote = self.codigo_lote.strip()
            self.clave_codigo = self._clave_para_codigo()
            if update_fields is not None:
                update_fields = {*update_fields, 'clave_codigo'}
        super().save(update_fields=update_fields, **kwargs)


class Movimiento(models.Model):
    class Tipo(models.TextChoices):
        INGRESO = 'ingreso', 'Ingreso'
        RETIRO = 'retiro', 'Retiro'

    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name='movimientos')
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='movimientos',
    )
    tipo = models.CharField(max_length=7, choices=Tipo)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    fecha_hora = models.DateTimeField('fecha y hora', auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad__gt=0, tipo__in=('ingreso', 'retiro')),
                name='movimiento_cantidad_y_tipo_validos',
            ),
        ]

