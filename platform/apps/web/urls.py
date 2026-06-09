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
    path("patients/<uuid:patient_id>/wallet/", views.wallet_txn, name="wallet_txn"),
    path("worklist/", views.worklist, name="worklist"),
    path("activity/", views.activity_log, name="activity"),
    # reception desk / invoicing (accounting port)
    path("reception/", views.reception, name="reception"),
    path("patients/<uuid:patient_id>/invoice/new/", views.invoice_open_for_patient, name="invoice_open_for_patient"),
    path("invoices/<uuid:invoice_id>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<uuid:invoice_id>/add-item/", views.invoice_add_item, name="invoice_add_item"),
    path("invoices/<uuid:invoice_id>/pay/", views.invoice_pay, name="invoice_pay"),
    path("invoices/<uuid:invoice_id>/close/", views.invoice_close, name="invoice_close"),
    path("tariffs/", views.tariffs, name="tariffs"),
    path("reports/", views.reports, name="reports"),
    path("reports/export.csv", views.reports_export_csv, name="reports_export_csv"),
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
