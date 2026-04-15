from django.urls import path
from . import views

urlpatterns = [
    path('generate/', views.GenerateView.as_view(), name='api_generate'),
    path('jobs/', views.JobListView.as_view(), name='api_job_list'),
    path('jobs/<uuid:pk>/', views.JobDetailView.as_view(), name='api_job_detail'),
    path('keys/', views.APIKeyListCreateView.as_view(), name='api_key_list'),
    path('keys/<uuid:pk>/', views.APIKeyDetailView.as_view(), name='api_key_detail'),
    path('status/', views.ModelStatusView.as_view(), name='api_status'),
]
