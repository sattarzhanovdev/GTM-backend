from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_alter_notification_apartment"),
    ]

    operations = [
        migrations.AddField(
            model_name="pushdevice",
            name="token_type",
            field=models.CharField(
                choices=[("expo", "Expo"), ("fcm", "FCM")],
                default="expo",
                max_length=10,
                verbose_name="Тип токена",
            ),
        ),
        migrations.AddIndex(
            model_name="pushdevice",
            index=models.Index(fields=["token_type"], name="api_pushdev_token_t_d9f802_idx"),
        ),
    ]

