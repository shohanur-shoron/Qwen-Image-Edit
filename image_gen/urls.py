from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('generate/', views.generate_view, name='generate'),
    path('jobs/', views.jobs_list, name='jobs_list'),
    path('jobs/<uuid:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<uuid:pk>/status/', views.job_status_api, name='job_status_api'),
    path('api-keys/', views.api_keys_view, name='api_keys'),
    path('api-keys/<uuid:pk>/revoke/', views.revoke_api_key, name='revoke_api_key'),
    path('api-keys/<uuid:pk>/delete/', views.delete_api_key, name='delete_api_key'),
    # Advanced features
    path('jobs/bulk-action/', views.bulk_action, name='bulk_action'),
    path('jobs/export/', views.export_jobs, name='export_jobs'),
    path('jobs/save-search/', views.save_search, name='save_search'),
    path('jobs/saved-search/<uuid:pk>/delete/', views.delete_saved_search, name='delete_saved_search'),
    path('jobs/create-tag/', views.create_tag, name='create_tag'),
    path('jobs/tag/<int:pk>/delete/', views.delete_tag, name='delete_tag'),
]
