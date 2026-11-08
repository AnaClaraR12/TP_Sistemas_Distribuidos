from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from simple_history.admin import SimpleHistoryAdmin

from apps.contas.models import User


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin, BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "nome", "papel", "is_active", "last_login", "ultimo_login_ip"]
    list_filter = ["papel", "is_active"]
    search_fields = ["email", "nome"]
    readonly_fields = ["last_login", "ultimo_login_ip", "date_joined"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("nome", "papel")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Acesso", {"fields": ("last_login", "ultimo_login_ip", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "nome", "papel", "password1", "password2")}),)
