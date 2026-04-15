from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import APIKey


class APIKeyAuthentication(BaseAuthentication):
    """
    Custom DRF authentication using an API key passed via the
    'X-API-Key' header or 'api_key' query parameter.
    """

    def authenticate(self, request):
        key = (
            request.META.get('HTTP_X_API_KEY')
            or request.query_params.get('api_key')
            or request.data.get('api_key')
        )

        if not key:
            return None  # let other authenticators try

        try:
            api_key = APIKey.objects.select_related('created_by').get(key=key, is_active=True)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid or revoked API key.')

        api_key.record_use()
        return (api_key.created_by, api_key)

    def authenticate_header(self, request):
        return 'X-API-Key'
