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
    path("worklist/", views.worklist, name="worklist"),
    path("followups/<uuid:task_id>/done/", views.followup_done, name="followup_done"),
    # e-prescription (Epic 1)
    path("patients/<uuid:patient_id>/rx/new/", views.rx_new, name="rx_new"),
    path("rx/<uuid:rx_id>/", views.rx_detail, name="rx_detail"),
    path("rx/<uuid:rx_id>/add-item/", views.rx_add_item, name="rx_add_item"),
    path("rx/<uuid:rx_id>/register/", views.rx_register, name="rx_register"),
]
