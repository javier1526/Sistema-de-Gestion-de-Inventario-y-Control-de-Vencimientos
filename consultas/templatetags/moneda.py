from django import template


register = template.Library()


@register.filter
def clp(valor):
    return f'${valor:,}'.replace(',', '.') + ' CLP'
