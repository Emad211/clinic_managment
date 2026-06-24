"""
Management command: onboard_tenant

تأمینِ (provisioning) یک tenant جدید + کاربرِ مدیرِ اولیه‌اش.

عملیات:
    ۱) رمز را با bcrypt hash می‌کند (در onboarding_service).
    ۲) platform.provision_tenant (SECURITY DEFINER) را از طریقِ Django
       connection (رولِ کم‌امتیازِ platform_app) صدا می‌زند.
    ۳) نتیجه را روی stdout چاپ می‌کند.

idempotent: اجرای مجدد با همان name → همان tenant_id، بدونِ خطا.

Usage:
    python manage.py onboard_tenant \\
        --name "کلینیک نمونه" \\
        --admin-username admin_clinic \\
        --password "SecurePass123" \\
        [--full-name "دکتر علی رضایی"]
"""
import getpass

from django.core.management.base import BaseCommand, CommandError

from platform_core.onboarding_service import provision_tenant, ProvisioningError


class Command(BaseCommand):
    help = (
        "Provision a new tenant + admin user. Idempotent — safe to re-run. "
        "Uses platform.provision_tenant (SECURITY DEFINER) via the app role."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            required=True,
            help="نامِ tenant (کلیدِ طبیعی؛ unique). مثال: «کلینیک نمونه»",
        )
        parser.add_argument(
            "--admin-username",
            dest="admin_username",
            required=True,
            help="نامِ کاربری مدیرِ اولیه. مثال: admin_clinic",
        )
        parser.add_argument(
            "--password",
            dest="password",
            default=None,
            help=(
                "رمزِ مدیر. اگر نداده شود، تعاملی پرسیده می‌شود "
                "(پیشنهاد می‌شود از stdin تعاملی استفاده شود، نه آرگومانِ command line)."
            ),
        )
        parser.add_argument(
            "--full-name",
            dest="full_name",
            default=None,
            help="نامِ کاملِ مدیر (اختیاری). مثال: «دکتر علی رضایی»",
        )

    def handle(self, *args, **options):
        tenant_name   = options["name"].strip()
        admin_username = options["admin_username"].strip()
        full_name     = (options["full_name"] or "").strip() or None

        # رمز: از آرگومان یا تعاملی
        password = options.get("password")
        if not password:
            try:
                password = getpass.getpass(
                    prompt=f"رمزِ مدیرِ '{admin_username}': "
                )
            except (EOFError, KeyboardInterrupt):
                raise CommandError("عملیات لغو شد.")

        if not password:
            raise CommandError("رمز نمی‌تواند خالی باشد.")

        self.stdout.write(
            self.style.NOTICE(
                f"در حالِ provisioning tenant '{tenant_name}' "
                f"با مدیرِ '{admin_username}' …"
            )
        )

        try:
            result = provision_tenant(
                name=tenant_name,
                admin_username=admin_username,
                password=password,
                admin_full_name=full_name,
            )
        except ProvisioningError as exc:
            raise CommandError(f"Provisioning ناموفق: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"\nProvisioning موفق:\n"
                f"  tenant_id    : {result['tenant_id']}\n"
                f"  tenant_name  : {result['tenant_name']}\n"
                f"  admin        : {result['admin_username']}\n"
                f"\nکاربر می‌تواند با این نامِ کاربری وارد شود."
            )
        )
