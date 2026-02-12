"""
URL configuration for Pricing Engine project.
"""

from django.contrib import admin
from django.urls import path, include

admin.site.site_header = "Pricing Engine Admin"
admin.site.site_title = "Admin Portal"
admin.site.index_title = "Welcome to the Pricing Manager"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pricing.urls')),
]
