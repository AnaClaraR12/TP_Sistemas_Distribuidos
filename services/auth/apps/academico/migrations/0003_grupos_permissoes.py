"""Data migration: grupos Administradores, Coordenadores, Professores, Alunos com permissões."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

PERMISSOES = {
    "Administradores": "__todas__",
    "Coordenadores": [
        "academico.add_curso",
        "academico.change_curso",
        "academico.view_curso",
        "academico.delete_curso",
        "academico.add_professor",
        "academico.change_professor",
        "academico.view_professor",
        "academico.delete_professor",
        "academico.add_aluno",
        "academico.change_aluno",
        "academico.view_aluno",
        "academico.delete_aluno",
        "auditoria.view_registroauditoria",
    ],
    "Professores": ["academico.view_curso", "academico.view_professor", "academico.view_aluno"],
    "Alunos": ["academico.view_curso", "academico.view_professor"],
}


def criar_grupos(apps, schema_editor):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for nome, perms in PERMISSOES.items():
        grupo, _ = Group.objects.get_or_create(name=nome)
        if perms == "__todas__":
            grupo.permissions.set(
                Permission.objects.filter(content_type__app_label__in=["academico", "auditoria", "contas"])
            )
            continue
        objs = []
        for codigo in perms:
            app_label, codename = codigo.split(".")
            objs.extend(Permission.objects.filter(content_type__app_label=app_label, codename=codename))
        grupo.permissions.set(objs)


def remover_grupos(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=PERMISSOES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("academico", "0002_initial"),
        ("auditoria", "0001_initial"),
        ("contas", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(criar_grupos, remover_grupos)]
