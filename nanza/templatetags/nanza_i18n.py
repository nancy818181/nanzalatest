"""Usage: {% load nanza_i18n %} {{ 'Invoice'|t }}."""
from django import template
from nanza.django_i18n import translate

register = template.Library()
register.filter("t", translate)
