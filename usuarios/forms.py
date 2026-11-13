from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .permisos import obtener_perfil


class FormularioInicioSesion(AuthenticationForm):
    error_messages = {
        'invalid_login': 'El usuario o la contraseña no son válidos.',
        'inactive': 'El usuario o la contraseña no son válidos.',
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].label = 'Usuario'
        self.fields['username'].widget.attrs.update({
            'autocomplete': 'username', 'autocapitalize': 'none',
            'spellcheck': 'false',
        })
        self.fields['password'].label = 'Contraseña'
        self.fields['password'].widget.attrs.update({
            'autocomplete': 'current-password',
        })
        for nombre, campo in self.fields.items():
            campo.widget.attrs['class'] = 'form-control'
            campo.error_messages['required'] = (
                f'El campo {campo.label.lower()} es obligatorio.'
            )
            campo.widget.attrs['aria-describedby'] = f'id_{nombre}_errores'

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if obtener_perfil(user) is None:
            raise forms.ValidationError(
                'Tu cuenta no tiene un perfil válido. '
                'Consulta al responsable de las cuentas.',
                code='perfil_invalido',
            )

