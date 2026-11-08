import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="EventoProcessado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.UUIDField(unique=True)),
                ("tipo", models.CharField(max_length=100)),
                ("processado_em", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "evento_processado"},
        ),
        migrations.CreateModel(
            name="OutboxEvento",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tipo", models.CharField(db_index=True, max_length=100)),
                ("payload", models.JSONField()),
                ("criado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("publicado_em", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("tentativas", models.PositiveIntegerField(default=0)),
                ("ultimo_erro", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "outbox",
                "ordering": ["criado_em"],
                "indexes": [models.Index(fields=["publicado_em", "criado_em"], name="outbox_pendentes_idx")],
            },
        ),
    ]
