from django.conf import settings
from django.core.cache import caches
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from environments.models import Environment

environment_cache = caches[settings.ENVIRONMENT_CACHE_LOCATION]


class EnvironmentKeyAuthentication(BaseAuthentication):
    """
    Custom authentication class to add the environment to the request for
    endpoints used by the clients.
    """

    def authenticate(self, request):
        api_key = request.META.get("HTTP_X_ENVIRONMENT_KEY")
        environment = Environment.get_from_cache(api_key)
        if not environment:
            raise AuthenticationFailed("Invalid or missing Environment Key")

        if environment.project.organisation.stop_serving_flags:
            raise AuthenticationFailed("Organisation is disabled from serving flags.")

        request.environment = environment

        # DRF authentication expects a two tuple to be returned containing User, auth
        return None, None
