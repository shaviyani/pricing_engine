from django.apps import AppConfig


class PricingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pricing'
    verbose_name = 'Pricing Engine'
    
    def ready(self):
        """Import signals when app is ready."""
        import pricing.signals  # noqa
