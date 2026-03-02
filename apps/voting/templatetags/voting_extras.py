"""
Custom template filters for the voting app.
"""
from django import template

register = template.Library()


@register.filter
def dictkey(d, key):
    """
    Look up a dictionary value by key in a template.

    Usage: {{ mydict|dictkey:post.pk }}
    Returns None if key is missing or input is not a dict.
    """
    if isinstance(d, dict):
        return d.get(key)
    return None
