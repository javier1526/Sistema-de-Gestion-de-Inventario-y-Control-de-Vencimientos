import re

from django import forms
from django.core.exceptions import ValidationError

from .models import Lote, Producto, clave_para_nombre, limpiar_nombre_producto
from .servicios import MENSAJE_CANTIDAD_RETIRO, validar_vencimiento_ingreso


MENSAJE_NOMBRE_DUPLICADO = 'Ya existe un producto con ese nombre.'
MENSAJE_STOCK_INVALIDO = 'El stock mínimo debe ser un número entero mayor que cero.'


class CampoEnteroEstricto(forms.IntegerField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip()
            if value and not re.fullmatch(r'[+-]?[0-9]+', value):
                raise ValidationError(self.error_messages['invalid'], code='invalid')
        return super().to_python(value)


class FormularioRetiro(forms.Form):
    cantidad = CampoEnteroEstricto(
        label='Cantidad que deseas retirar', min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
        error_messages={
            'required': 'Indica la cantidad que deseas retirar.',
            'invalid': MENSAJE_CANTIDAD_RETIRO,
            'min_value': MENSAJE_CANTIDAD_RETIRO,
        },
    )


class FormularioProducto(forms.ModelForm):
    stock_minimo = CampoEnteroEstricto(
        label='Stock mínimo', min_value=1,
        max_value=2_147_483_647,
        error_messages={
            'required': 'Indica el stock mínimo.',
            'invalid': MENSAJE_STOCK_INVALIDO,
            'min_value': MENSAJE_STOCK_INVALIDO,
            'max_value': 'El stock mínimo no puede superar 2147483647.',
        },
    )

    class Meta:
        model = Producto
        fields = ('nombre', 'stock_minimo')
        labels = {'nombre': 'Nombre del producto'}
        error_messages = {'nombre': {'required': 'Indica el nombre del producto.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'form-control'

    def nombre_duplicado(self, nombre):
        return Producto.objects.filter(clave_nombre=clave_para_nombre(nombre)).exclude(
            pk=self.instance.pk,
        ).exists()

    def clean_nombre(self):
        nombre = limpiar_nombre_producto(self.cleaned_data['nombre'])
        if self.nombre_duplicado(nombre):
            raise ValidationError(MENSAJE_NOMBRE_DUPLICADO, code='duplicado')
        return nombre


class FormularioIngreso(forms.ModelForm):
    fecha_vencimiento = forms.DateField(
        label='Fecha de vencimiento', input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        validators=[validar_vencimiento_ingreso],
        error_messages={
            'required': 'Indica la fecha de vencimiento.',
            'invalid': 'Indica una fecha de vencimiento válida.',
        },
    )
    cantidad_ingresada = CampoEnteroEstricto(
        label='Cantidad recibida', min_value=1, max_value=2_147_483_647,
        error_messages={
            'required': 'Indica la cantidad recibida.',
            'invalid': 'La cantidad debe ser un número entero mayor que cero.',
            'min_value': 'La cantidad debe ser un número entero mayor que cero.',
        },
    )
    costo_unitario_clp = CampoEnteroEstricto(
        label='Costo unitario de adquisición (CLP)', min_value=1,
        max_value=2_147_483_647,
        error_messages={
            'required': 'Indica el costo unitario de adquisición.',
            'invalid': 'El costo debe ser un número entero mayor que cero en CLP.',
            'min_value': 'El costo debe ser un número entero mayor que cero en CLP.',
        },
    )

    class Meta:
        model = Lote
        fields = (
            'producto', 'codigo_lote', 'fecha_vencimiento',
            'cantidad_ingresada', 'costo_unitario_clp',
        )
        error_messages = {
            'producto': {
                'required': 'Selecciona un producto.',
                'invalid_choice': 'El producto seleccionado no existe.',
            },
            'codigo_lote': {'required': 'Indica el código de lote.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].empty_label = 'Selecciona un producto'
        for nombre, campo in self.fields.items():
            campo.widget.attrs['class'] = (
                'form-select' if nombre == 'producto' else 'form-control'
            )
