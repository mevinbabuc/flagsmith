from features.models import Feature, FeatureState
from integrations.webhook.serializers import IntegrationFeatureStateSerializer
from integrations.webhook.webhook import WebhookWrapper


def test_webhook_generate_user_data(
    integration_webhook_config, organisation_one_project_one, identity
):
    # Given
    webhook_wrapper = WebhookWrapper(integration_webhook_config)

    feature = Feature.objects.create(
        name="Test Feature", project=organisation_one_project_one
    )

    feature_states = FeatureState.objects.filter(feature=feature)
    expected_flags = IntegrationFeatureStateSerializer(
        feature_states, many=True, context={"identity": identity}
    ).data
    user_data = webhook_wrapper.generate_user_data(
        identity=identity, feature_states=feature_states
    )
    expected_data = {
        "identity": identity.identifier,
        "traits": [],
        "segments": [],
        "flags": expected_flags,
    }
    assert expected_data == user_data
