from django.db import migrations


def make_au_signature_json_safe(apps, schema_editor):
    """Wrap non-JSON au_signature values so they become valid JSON strings."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE emotion_detection_interventionrecord
            SET au_signature = JSON_QUOTE(au_signature)
            WHERE au_signature IS NOT NULL
              AND JSON_VALID(au_signature) = 0
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("emotion_detection", "0006_interventionrecord_alter_customeremotion_options_and_more"),
    ]

    operations = [
        migrations.RunPython(make_au_signature_json_safe, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE emotion_detection_interventionrecord "
                "DROP INDEX IF EXISTS idx_emotion_au"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="ALTER TABLE emotion_detection_interventionrecord MODIFY au_signature LONGTEXT",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
