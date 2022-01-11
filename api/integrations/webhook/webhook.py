import logging
import typing

import requests

import features
from environments.identities import (
    traits,  # .serializers import TraitSerializerBasic
)
from integrations.common.wrapper import AbstractBaseIdentityIntegrationWrapper

from .serializers import SegmentSerializer

if typing.TYPE_CHECKING:
    from environments.identities.models import Identity
    from features.models import FeatureState

logger = logging.getLogger(__name__)


class WebhookWrapper(AbstractBaseIdentityIntegrationWrapper):
    def __init__(self, url, secret):
        self.url = url
        self.secret = secret

    def _identify_user(self, user_data: dict) -> None:
        response = requests.post(self.url, json=user_data)
        logger.debug(
            "Sent event to Webhook. Response code was: %s" % response.status_code
        )

    def generate_user_data(
        self, identity: "Identity", feature_states: typing.List["FeatureState"]
    ) -> dict:
        feature_properties = {}

        for feature_state in feature_states:
            value = feature_state.get_feature_state_value(identity=identity)
            feature_properties[feature_state.feature.name] = (
                value if (feature_state.enabled and value) else feature_state.enabled
            )
        serialized_flags = features.serializers.FeatureStateSerializerFull(
            feature_states, many=True, context={"identity": identity}
        )
        serialized_traits = traits.serializers.TraitSerializerBasic(
            identity.identity_traits.all(), many=True
        )
        serialized_segments = SegmentSerializer(
            identity.environment.project.get_segments_from_cache(), many=True
        )

        data = {
            "identity": identity.identifier,
            "traits": serialized_traits.data,
            "flags": serialized_flags.data,
            "segments": serialized_segments.data,
        }
        breakpoint()
        return data
