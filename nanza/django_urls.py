"""Include from the real Django host URLconf, if one is added."""
from django.urls import path
from nanza.django_i18n import set_language

urlpatterns = [path("language/", set_language, name="nanza_set_language")]
