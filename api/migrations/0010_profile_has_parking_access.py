from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0009_expenses_and_fund_opening_balance"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="has_parking_access",
            field=models.BooleanField(default=False, verbose_name="Доступ к парковке"),
        ),
    ]

