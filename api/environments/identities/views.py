import base64
import json
import typing
from collections import namedtuple

import coreapi
from boto3.dynamodb.conditions import BeginsWith, Equals, Key
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.schemas import AutoSchema

from app.pagination import IdentityPagination
from environments.identities.helpers import identify_integrations
from environments.identities.models import Identity
from environments.identities.serializers import IdentitySerializer
from environments.identities.traits.serializers import TraitSerializerBasic
from environments.models import Environment
from environments.permissions.permissions import NestedEnvironmentPermissions
from environments.sdk.serializers import (
    IdentifyWithTraitsSerializer,
    IdentitySerializerWithTraitsAndSegments,
)
from features.serializers import FeatureStateSerializerFull
from util.views import SDKAPIView


class IdentityViewSet(viewsets.ModelViewSet):
    serializer_class = IdentitySerializer
    permission_classes = [IsAuthenticated, NestedEnvironmentPermissions]
    pagination_class = IdentityPagination
    lookup_field = "identifier"

    def get_object(self):
        identifier = self.kwargs["identifier"]
        environment = self.get_environment_from_request()
        if environment.project.enable_dynamo_db:
            key = {"composite_key": f"{environment.api_key}_{identifier}"}
            return Identity.get_item_dynamodb(key)
        return Identity.objects.get(environment=environment, identifier=identifier)

    @staticmethod
    def _get_search_expression_dynamo(
        search_query: str,
    ) -> typing.Union[Equals, BeginsWith]:
        if search_query.startswith('"') and search_query.endswith('"'):
            return Key("identifier").eq(search_query.replace('"', ""))
        else:
            return Key("identifier").begins_with(search_query)

    @staticmethod
    def _get_search_kwargs_django(search_query: str) -> dict:
        filter_kwargs = {}
        if search_query.startswith('"') and search_query.endswith('"'):
            filter_kwargs["identifier__exact"] = search_query.replace('"', "")
        else:
            filter_kwargs["identifier__icontains"] = search_query

        return filter_kwargs

    def get_queryset(self):
        environment = self.get_environment_from_request()

        search_query = self.request.query_params.get("q")
        queryset = Identity.objects.filter(environment=environment)

        if search_query:
            filter_kwargs = self._get_search_kwargs_django(search_query)
            queryset = queryset.filter(**filter_kwargs)
        # change the default order by to avoid performance issues with pagination
        # when environments have small number (<page_size) of records
        queryset = queryset.order_by("created_date")

        return queryset

    def get_queryset_dynamodb(self, page_size):
        dynamo_query_kwargs = self._get_dynamo_query_kwargs(page_size)
        return Identity.query_items_dynamodb(**dynamo_query_kwargs)

    def _get_dynamo_query_kwargs(
        self,
        page_size: int,
    ) -> dict:
        search_query = self.request.query_params.get("q")
        previous_last_evaluated_key = self.request.GET.get("last_evaluated_key")

        filter_expression = Key("environment_api_key").eq(
            self.kwargs["environment_api_key"]
        )
        if search_query:
            filter_expression = filter_expression & self._get_search_expression_dynamo(
                search_query
            )

        dynamo_query_kwargs = {
            "IndexName": "environment_api_key-identifier-index",
            "Limit": page_size,
            "KeyConditionExpression": filter_expression,
        }
        if previous_last_evaluated_key:
            dynamo_query_kwargs.update(
                ExclusiveStartKey=json.loads(
                    base64.b64decode(previous_last_evaluated_key)
                )
            )
        return dynamo_query_kwargs

    def _get_list_response_from_dynamo(self, request):
        paginator = self.pagination_class()
        page_size = paginator.get_page_size(request)
        dynamo_query_set = self.get_queryset_dynamodb(page_size)
        paginator.set_pagination_state_dynamo(dynamo_query_set, request)

        serializer = IdentitySerializer(data=dynamo_query_set["Items"], many=True)
        serializer.is_valid()
        return paginator.get_paginated_response_dynamo(serializer.data)

    def list(self, request, *args, **kwargs):
        environment = self.get_environment_from_request()
        if not environment.project.enable_dynamo_db:
            return super().list(request, *args, **kwargs)
        return self._get_list_response_from_dynamo(request)

    def get_environment_from_request(self):
        """
        Get environment object from URL parameters in request.
        """
        return Environment.objects.get(api_key=self.kwargs["environment_api_key"])

    def perform_create(self, serializer):
        environment = self.get_environment_from_request()
        if environment.project.enable_dynamo_db:
            Identity.put_item_dynamodb({**serializer.data, **self.kwargs})
            return
        serializer.save(environment=environment)

    def perform_destroy(self, instance):
        environment = self.get_environment_from_request()
        if environment.project.enable_dynamo_db:
            Identity.delete_in_dynamodb(instance.composite_key)
            return
        super().perform_destroy(instance)

    def perform_update(self, serializer):
        environment = self.get_environment_from_request()
        if environment.project.enable_dynamo_db:
            Identity.put_item_dynamodb({**serializer.data, **self.kwargs})
            return
        serializer.save(environment=environment)


class SDKIdentitiesDeprecated(SDKAPIView):
    """
    THIS ENDPOINT IS DEPRECATED. Please use `/identities/?identifier=<identifier>` instead.
    """

    # API to handle /api/v1/identities/ endpoint to return Flags and Traits for user Identity
    # if Identity does not exist it will create one, otherwise will fetch existing

    serializer_class = IdentifyWithTraitsSerializer

    schema = AutoSchema(
        manual_fields=[
            coreapi.Field(
                "X-Environment-Key",
                location="header",
                description="API Key for an Environment",
            ),
            coreapi.Field(
                "identifier",
                location="path",
                required=True,
                description="Identity user identifier",
            ),
        ]
    )

    # identifier is in a path parameter
    def get(self, request, identifier, *args, **kwargs):
        # if we have identifier fetch, or create if does not exist
        if identifier:
            identity, _ = Identity.objects.get_or_create(
                identifier=identifier,
                environment=request.environment,
            )

        else:
            return Response(
                {"detail": "Missing identifier"}, status=status.HTTP_400_BAD_REQUEST
            )

        if identity:
            traits_data = identity.get_all_user_traits()
            # traits_data = self.get_serializer(identity.get_all_user_traits(), many=True)
            # return Response(traits.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"detail": "Given identifier not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # We need object type to pass into our IdentitySerializerTraitFlags
        IdentityFlagsWithTraitsAndSegments = namedtuple(
            "IdentityTraitFlagsSegments", ("flags", "traits", "segments")
        )
        identity_flags_traits_segments = IdentityFlagsWithTraitsAndSegments(
            flags=identity.get_all_feature_states(),
            traits=traits_data,
            segments=identity.get_segments(),
        )

        serializer = IdentitySerializerWithTraitsAndSegments(
            identity_flags_traits_segments
        )

        return Response(serializer.data, status=status.HTTP_200_OK)


class SDKIdentities(SDKAPIView):
    serializer_class = IdentifyWithTraitsSerializer
    pagination_class = None  # set here to ensure documentation is correct

    def get(self, request):
        identifier = request.query_params.get("identifier")
        if not identifier:
            return Response(
                {"detail": "Missing identifier"}
            )  # TODO: add 400 status - will this break the clients?

        identity, _ = (
            Identity.objects.select_related("environment", "environment__project")
            .prefetch_related("identity_traits", "environment__project__segments")
            .get_or_create(identifier=identifier, environment=request.environment)
        )

        feature_name = request.query_params.get("feature")
        if feature_name:
            return self._get_single_feature_state_response(identity, feature_name)
        else:
            return self._get_all_feature_states_for_user_response(identity)

    def get_serializer_context(self):
        context = super(SDKIdentities, self).get_serializer_context()
        if hasattr(self.request, "environment"):
            # only set it if the request has the attribute to ensure that the
            # documentation works correctly still
            context["environment"] = self.request.environment
        return context

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        # we need to serialize the response again to ensure that the
        # trait values are serialized correctly
        response_serializer = IdentifyWithTraitsSerializer(
            instance=instance,
            context={"identity": instance.get("identity")},  # todo: improve this
        )
        return Response(response_serializer.data)

    def _get_single_feature_state_response(self, identity, feature_name):
        for feature_state in identity.get_all_feature_states():
            if feature_state.feature.name == feature_name:
                serializer = FeatureStateSerializerFull(
                    feature_state, context={"identity": identity}
                )
                return Response(data=serializer.data, status=status.HTTP_200_OK)

        return Response(
            {"detail": "Given feature not found"}, status=status.HTTP_404_NOT_FOUND
        )

    def _get_all_feature_states_for_user_response(self, identity, trait_models=None):
        """
        Get all feature states for an identity

        :param identity: Identity model to return feature states for
        :param trait_models: optional list of trait_models to pass in for organisations that don't persist them
        :return: Response containing lists of both serialized flags and traits
        """
        all_feature_states = identity.get_all_feature_states()
        serialized_flags = FeatureStateSerializerFull(
            all_feature_states, many=True, context={"identity": identity}
        )
        serialized_traits = TraitSerializerBasic(
            identity.identity_traits.all(), many=True
        )

        identify_integrations(identity, all_feature_states)

        response = {"flags": serialized_flags.data, "traits": serialized_traits.data}

        return Response(data=response, status=status.HTTP_200_OK)
