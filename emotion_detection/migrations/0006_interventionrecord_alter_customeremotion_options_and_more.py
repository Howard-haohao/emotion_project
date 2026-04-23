from django.db import migrations, models


def _safe_execute(cursor, sql):
    try:
        cursor.execute(sql)
    except Exception:
        # Ignore errors if the column/index already exists or is incompatible.
        pass


def upgrade_interventionrecord(apps, schema_editor):
    table = "emotion_detection_interventionrecord"
    with schema_editor.connection.cursor() as cursor:
        _safe_execute(
            cursor,
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS score double DEFAULT 0",
        )
        _safe_execute(
            cursor,
            f"ALTER TABLE {table} MODIFY emotion_label varchar(20) NOT NULL",
        )
        _safe_execute(
            cursor,
            f"ALTER TABLE {table} MODIFY au_signature JSON NOT NULL",
        )
        _safe_execute(
            cursor,
            f"ALTER TABLE {table} MODIFY source varchar(20) NOT NULL DEFAULT 'auto'",
        )
        _safe_execute(
            cursor,
            f"ALTER TABLE {table} MODIFY notes varchar(20) NOT NULL DEFAULT ''",
        )
        cursor.execute(
            """
            SELECT INDEX_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND NON_UNIQUE = 0
            GROUP BY INDEX_NAME
            HAVING SUM(CASE WHEN COLUMN_NAME='session_label' THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN COLUMN_NAME='analysis_date' THEN 1 ELSE 0 END) > 0
            """,
            [table],
        )
        for (index_name,) in cursor.fetchall():
            _safe_execute(cursor, f"DROP INDEX {index_name} ON {table}")


def add_au_columns(apps, schema_editor):
    table = "emotion_detection_customeremotion"
    with schema_editor.connection.cursor() as cursor:
        for i in range(1, 46):
            col = f"au{str(i).zfill(2)}"
            _safe_execute(
                cursor,
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} double DEFAULT 0",
            )


class Migration(migrations.Migration):

    dependencies = [
        ("emotion_detection", "0005_delete_uploadedimage_customeremotion_created_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="InterventionRecord",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("session_label", models.CharField(max_length=100)),
                        ("analysis_date", models.DateField()),
                        ("average_score", models.FloatField(default=0.0)),
                        ("score", models.FloatField(default=0.0)),
                        ("emotion_label", models.CharField(max_length=20)),
                        ("au_signature", models.JSONField(default=dict)),
                        ("frames", models.JSONField(blank=True, default=list)),
                        ("suggestions", models.JSONField(blank=True, default=list)),
                        ("source", models.CharField(default="auto", max_length=20)),
                        ("is_template", models.BooleanField(default=False)),
                        ("usage_count", models.PositiveIntegerField(default=0)),
                        ("needs_intervention", models.BooleanField(default=False)),
                        ("notes", models.CharField(default="", max_length=20)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "ordering": ["-analysis_date", "-updated_at"],
                    },
                ),
            ],
            database_operations=[
                migrations.RunPython(upgrade_interventionrecord, migrations.RunPython.noop),
            ],
        ),
        migrations.AlterModelOptions(
            name="customeremotion",
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(add_au_columns, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customeremotion",
            name="emotion_data",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
