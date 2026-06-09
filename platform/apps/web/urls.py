from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.index, name="index"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("patients/", views.patient_list, name="patients"),
    path("patients/<uuid:patient_id>/", views.patient_detail, name="patient_detail"),
    path("patients/<uuid:patient_id>/ack/", views.acknowledge_suggestion, name="ack"),
    path("worklist/", views.worklist, name="worklist"),
    # billing / subscription
    path("billing/", views.billing_home, name="billing"),
    path("billing/subscribe/<uuid:plan_id>/", views.billing_subscribe, name="billing_subscribe"),
    path("billing/callback/", views.billing_callback, name="billing_callback"),
    path("followups/<uuid:task_id>/done/", views.followup_done, name="followup_done"),
    path("followups/<uuid:task_id>/remind/", views.followup_remind, name="followup_remind"),
    # e-prescription (Epic 1)
    path("patients/<uuid:patient_id>/rx/new/", views.rx_new, name="rx_new"),
    path("rx/<uuid:rx_id>/", views.rx_detail, name="rx_detail"),
    path("rx/<uuid:rx_id>/add-item/", views.rx_add_item, name="rx_add_item"),
    path("rx/<uuid:rx_id>/register/", views.rx_register, name="rx_register"),
]
