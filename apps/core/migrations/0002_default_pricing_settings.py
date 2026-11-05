from django.db import migrations


def create_default_pricing_settings(apps, schema_editor):
    pricing_settings = apps.get_model("core", "PricingSettings")
    pricing_settings.objects.using(schema_editor.connection.alias).get_or_create(pk=1)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_default_pricing_settings,
            migrations.RunPython.noop,
        ),
    ]
