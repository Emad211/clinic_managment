"""Create a clinic (tenant) + its first manager user.

    python manage.py bootstrap_clinic --name "درمانگاه نمونه" --slug demo \
        --admin-username admin --admin-password admin

Password is bcrypt-hashed (same scheme as the Flask apps' auth_service, which
also migrates legacy werkzeug hashes to bcrypt on login). Idempotent on
(slug) and (clinic, username).

PostgreSQL note: app_user is RLS-protected. Creating the FIRST user of a clinic
is a chicken-and-egg case — run this under the platform owner/BYPASSRLS ops role,
not a tenant role.
"""

import bcrypt
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.identity.models import AppUser, Clinic


class Command(BaseCommand):
    help = "Create a clinic tenant and its first manager user (bcrypt)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-password", default="admin")
        parser.add_argument("--province", default="")
        parser.add_argument("--city", default="")
        parser.add_argument(
            "--license", default="",
            help="نظام‌پزشکی license no. for the manager — set it when the owner "
                 "is also the practising physician so they can sign clinical "
                 "decisions (acknowledge suggestions, e-prescribe).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        clinic, created = Clinic.objects.get_or_create(
            slug=opts["slug"],
            defaults={
                "name": opts["name"],
                "status": "trial",
                "province": opts["province"],
                "city": opts["city"],
            },
        )
        verb = "Created" if created else "Found existing"
        # Keep stdout ASCII-only: a non-UTF-8 console (e.g. Windows cp1252) would
        # raise UnicodeEncodeError on the Persian clinic name and roll back this
        # atomic transaction. The name is stored correctly in the DB regardless.
        self.stdout.write(f"{verb} clinic (slug={clinic.slug}, id={clinic.id})")

        pw_hash = bcrypt.hashpw(opts["admin_password"].encode("utf-8"), bcrypt.gensalt())
        user, u_created = AppUser.objects.get_or_create(
            clinic=clinic,
            username=opts["admin_username"],
            defaults={
                "password_hash": pw_hash,
                "role": "clinic_manager",
                "full_name": "مدیر کلینیک",
                "medical_license_no": opts["license"],
                "is_active": True,
            },
        )
        if u_created:
            self.stdout.write(self.style.SUCCESS(
                f"Created manager '{user.username}' for clinic {clinic.slug}."
            ))
        else:
            self.stdout.write(f"Manager '{user.username}' already exists - left unchanged.")
