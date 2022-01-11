from rest_framework import serializers

from integrations import (
    webhook,  # import models  # import WebhookConfiguration
)

# from segments.models import Segment


class WebhookConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = webhook.models.WebhookConfiguration
        fields = ("url", "secret")


class SegmentSerializer(serializers.Serializer):
    member = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    name = serializers.CharField()

    def get_member(self, obj):
        return obj.does_identity_match(identity=self.context.get("identity"))

    # class Meta:
    #     model = Segment
    #     fields = ("name", "id")
