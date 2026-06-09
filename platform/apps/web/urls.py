from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("patients/", views.patient_list, name="patients"),
    path("patients/<uuid:patient_id>/", views.patient_detail, name="patient_detail"),
    path("patients/<uuid:patient_id>/ack/", views.acknowledge_suggestion, name="ack"),
]
