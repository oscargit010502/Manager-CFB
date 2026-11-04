from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import User, Group
from .models import AuditEvent

# Business writes go through application services. Admin manages users/groups only.
admin.site.site_header = 'Casa Funeraria Baranoa · Administración'
admin.site.site_title = 'Administración privada'
admin.site.index_title = 'Usuarios, permisos y auditoría'

class SuperuserManagementMixin:
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission
    has_delete_permission = has_view_permission


admin.site.unregister(User)
admin.site.unregister(Group)

@admin.register(User)
class PrivateUserAdmin(SuperuserManagementMixin, UserAdmin):
    pass

@admin.register(Group)
class PrivateGroupAdmin(SuperuserManagementMixin, GroupAdmin):
    pass

@admin.register(AuditEvent)
class AuditAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'actor', 'case', 'action']
    list_filter = ['action', 'created_at']
    search_fields = ['case__deceased_name', 'detail']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
