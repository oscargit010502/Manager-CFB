from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path
from core import views, finance_views as finance, dashboard_views as dashboard
from core.auth_views import PrivateLoginView

urlpatterns = [
    path('ingresar/', PrivateLoginView.as_view(), name='login'),
    path('salir/', auth.LogoutView.as_view(), name='logout'),
    path('clave/', auth.PasswordChangeView.as_view(), name='password_change'),
    path('clave/listo/', auth.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('admin/login/', PrivateLoginView.as_view(), name='admin_login'),
    path('admin/', admin.site.urls),
    path('', dashboard.dashboard, name='dashboard'),
    path('expedientes/', dashboard.case_list, name='case_list'),
    path('expedientes/nuevo/', views.case_create, name='case_create'),
    path('expedientes/<int:pk>/', views.case_detail, name='case_detail'),
    path('expedientes/<int:pk>/editar/', views.case_edit, name='case_edit'),
    path('expedientes/<int:pk>/iniciar/', views.case_start, name='case_start'),
    path('expedientes/<int:pk>/cerrar/', views.case_close, name='case_close'),
    path('expedientes/<int:pk>/cancelar/', views.case_cancel, name='case_cancel'),
    path('expedientes/<int:pk>/reabrir/', views.case_reopen, name='case_reopen'),
    path('expedientes/<int:pk>/servicios/nuevo/', views.service_add, name='service_add'),
    path('servicios/<int:item_id>/editar/', views.service_update, name='service_update'),
    path('servicios/<int:item_id>/prestacion/', views.service_toggle, name='service_toggle'),
    path('expedientes/<int:pk>/tramites/nuevo/', views.procedure_add, name='procedure_add'),
    path('tramites/<int:procedure_id>/', views.procedure_update, name='procedure_update'),
    path('expedientes/<int:pk>/documentos/nuevo/', views.document_upload, name='document_upload'),
    path('documentos/<int:document_id>/', views.document_download, name='document_download'),
    path('expedientes/<int:pk>/requisitos/nuevo/', views.requirement_add, name='requirement_add'),
    path('empresas/', views.partner_list, name='partner_list'),
    path('empresas/nueva/', views.partner_create, name='partner_create'),
    path('empresas/<int:pk>/editar/', views.partner_edit, name='partner_edit'),
    path('configuracion/', views.company_settings, name='company_settings'),
    path('configuracion/logo/', views.company_logo, name='company_logo'),
    path('expedientes/<int:case_id>/facturas/nueva/', finance.invoice_create, name='invoice_create'),
    path('facturas/<int:invoice_id>/abonos/nuevo/', finance.payment_create, name='payment_create'),
    path('facturas/<int:invoice_id>/anular/', finance.invoice_void, name='invoice_void'),
    path('abonos/<int:payment_id>/anular/', finance.payment_void, name='payment_void'),
    path('expedientes/<int:case_id>/costos/nuevo/', finance.cost_create, name='cost_create'),
    path('costos/<int:cost_id>/anular/', finance.cost_void, name='cost_void'),
]
