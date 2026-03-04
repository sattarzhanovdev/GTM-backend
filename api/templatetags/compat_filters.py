from __future__ import annotations

from django import template

register = template.Library()


@register.filter(name="length_is")
def length_is(value, arg) -> bool:
    """
    Совместимость для сторонних шаблонов (например Jazzmin), которые всё ещё
    используют удалённый в Django 5.1 фильтр `length_is`.
    """
    try:
        length = len(value)
    except Exception:
        length = 0

    try:
        expected = int(arg)
    except Exception:
        expected = arg

    return length == expected
