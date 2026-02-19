"""
URL configuration for Pricing Engine project.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

admin.site.site_header = "Pricing Engine Admin"
admin.site.site_title = "Admin Portal"
admin.site.index_title = "Welcome to the Pricing Manager"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('platform/', include('platform_data.urls')),
    path('', include('pricing.urls')),
]
