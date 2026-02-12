"""
URL configuration package.

Combines all URL patterns from the 4 pillars into a single
urlpatterns list. The app_name stays 'pricing' for namespace.
"""

from .core import urlpatterns as core_urls
from .pricing import urlpatterns as pricing_urls
from .analytics import urlpatterns as analytics_urls
from .forecasts import urlpatterns as forecast_urls
from .admin import urlpatterns as admin_urls

app_name = 'pricing'

urlpatterns = (
    core_urls
    + pricing_urls
    + analytics_urls
    + forecast_urls
    + admin_urls
)
