"""URL configuration for halqe platform."""
from django.urls import path
from config.api import api

urlpatterns = [
    path("api/v1/", api.urls),
]
