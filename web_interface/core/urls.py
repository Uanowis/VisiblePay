from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('cards/', views.cards, name='cards'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('api/sms-webhook/', views.sms_webhook, name='sms_webhook'),
    path('test/', views.test_runner, name='test_runner'),
    path('api/start-test/', views.start_test, name='start_test'),
    path('api/test-status/<int:test_run_id>/', views.get_test_status, name='get_test_status'),
    path('cards/edit/<int:pk>/', views.edit_card, name='edit_card'),
    path('cards/delete/<int:pk>/', views.delete_card, name='delete_card'),
    path('cards/top-up/<int:pk>/', views.top_up_card, name='top_up_card'),
    path('sms-logs/', views.sms_logs, name='sms_logs'),
    path('api/init-transaction/', views.init_transaction, name='init_transaction'),
    path('api/check-transaction-status/<int:task_id>/', views.check_transaction_status_api, name='check_transaction_status'),
    path('api/complete-transaction/', views.complete_transaction, name='complete_transaction'),
    path('tl-yukle/', views.tl_load, name='tl_load'),
    path('api/start-tl-test/', views.start_tl_test, name='start_tl_test'),
    path('bulk-orders/', views.bulk_orders, name='bulk_orders'),
    path('auto-orders/', views.auto_orders, name='auto_orders'),
    path('auto-orders/settings/', views.update_system_settings, name='update_system_settings'),
    path('auto-orders/define-package/', views.define_package, name='define_package'),
    path('auto-orders/cancel/', views.cancel_order, name='cancel_order'),
    path('packages/', views.packages, name='packages'),
    path('packages/edit/<int:pk>/', views.edit_package, name='edit_package'),
    path('packages/delete/<int:pk>/', views.delete_package, name='delete_package'),
]
