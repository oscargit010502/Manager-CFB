from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """Display COP with Colombian thousands and decimal separators."""
    try:
        amount = Decimal(str(value or 0))
        if not amount.is_finite():
            return "—"
        formatted = f"{amount:,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "—"
    return "$ " + formatted.translate(str.maketrans({",": ".", ".": ","}))
