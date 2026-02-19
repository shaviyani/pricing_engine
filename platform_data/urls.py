"""Platform Data URL patterns: Dashboard, org/property management, signal upload."""

from django.urls import path
from . import views

app_name = 'platform'

urlpatterns = [
    # Dashboard
    path('', views.PlatformDashboardView.as_view(), name='dashboard'),
    
    # Organizations
    path('organizations/', views.PlatformOrganizationsView.as_view(), name='organizations'),
    path('organizations/<int:pk>/', views.PlatformOrgDetailView.as_view(), name='org_detail'),
    
    # Organization API (CRUD)
    path('api/organizations/create/', views.PlatformOrgCreateView.as_view(), name='org_create'),
    path('api/organizations/<int:pk>/update/', views.PlatformOrgUpdateView.as_view(), name='org_update'),
    path('api/organizations/<int:pk>/delete/', views.PlatformOrgDeleteView.as_view(), name='org_delete'),
    
    # Property API (CRUD)
    path('api/properties/', views.PlatformPropertyListAPIView.as_view(), name='property_list_api'),
    path('api/properties/create/', views.PlatformPropertyCreateView.as_view(), name='property_create'),
    path('api/properties/<int:pk>/update/', views.PlatformPropertyUpdateView.as_view(), name='property_update'),
    path('api/properties/<int:pk>/delete/', views.PlatformPropertyDeleteView.as_view(), name='property_delete'),
    
    # Signals (market data)
    path('signals/', views.PlatformSignalsView.as_view(), name='signals'),
    
    # Signal API
    path('api/signals/upload/', views.PlatformSignalUploadView.as_view(), name='signal_upload'),
    path('api/signals/execute/', views.PlatformSignalExecuteView.as_view(), name='signal_execute'),
    path('api/signals/templates/', views.PlatformTemplateListView.as_view(), name='template_list'),
    path('api/signals/templates/save/', views.PlatformTemplateSaveView.as_view(), name='template_save'),
    path('api/signals/templates/<int:pk>/delete/', views.PlatformTemplateDeleteView.as_view(), name='template_delete'),
    
    # Arrival data
    path('api/arrivals/', views.PlatformArrivalDataView.as_view(), name='arrivals_api'),
    
    # Events
    path('api/events/', views.PlatformEventListView.as_view(), name='events_api'),
    path('api/events/create/', views.PlatformEventCreateView.as_view(), name='event_create'),
    path('api/events/<int:pk>/update/', views.PlatformEventUpdateView.as_view(), name='event_update'),
    path('api/events/<int:pk>/delete/', views.PlatformEventDeleteView.as_view(), name='event_delete'),
]
