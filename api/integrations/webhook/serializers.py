from django.db.models import Q
from rest_framework import serializers

from features.serializers import FeatureStateSerializerFull

from .models import WebhookConfiguration


class WebhookConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookConfiguration
        fields = ("url", "secret")


class SegmentSerializer(serializers.Serializer):
    member = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    name = serializers.CharField()

    def get_member(self, obj):
        return obj.does_identity_match(identity=self.context.get("identity"))


class IntegrationFeatureStateSerializer(FeatureStateSerializerFull):
    environment_weight = serializers.SerializerMethodField()

    def get_environment_weight(self, obj):
        value = self.get_feature_state_value(obj)
        value_filter = Q(multivariate_feature_option__string_value=value)
        if isinstance(value, int):
            value_filter = Q(multivariate_feature_option__integer_value=value)

        if isinstance(value, bool):
            value_filter = Q(multivariate_feature_option__boolean_value=value)
        mv_fs = obj.multivariate_feature_state_values.filter(value_filter).first()
        if mv_fs:
            return mv_fs.percentage_allocation
