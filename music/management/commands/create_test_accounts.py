from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update demo/admin test accounts."

    def handle(self, *args, **options):
        User = get_user_model()

        demo, demo_created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com", "is_active": True},
        )
        demo.is_staff = False
        demo.is_superuser = False
        demo.is_active = True
        demo.set_password("demo@123")
        demo.save()

        admin, admin_created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.is_active = True
        admin.set_password("admin@123")
        admin.save()

        demo_status = "created" if demo_created else "updated"
        admin_status = "created" if admin_created else "updated"
        self.stdout.write(self.style.SUCCESS(f"demo account {demo_status}: demo / demo@123"))
        self.stdout.write(self.style.SUCCESS(f"admin account {admin_status}: admin / admin@123"))
