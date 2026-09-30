"""
API Views for Fuel Route Optimization.
Keep the view thin: coordinates request validation and calls the service layer.
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_route.serializers import RouteRequestSerializer
from fuel_route.services.planner import plan_fuel_route


class RoutePlanView(APIView):
    """
    POST /api/v1/route/
    Calculates the optimal fuel stops along a driving route between two US locations.
    """

    def post(self, request, *args, **kwargs):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = plan_fuel_route(
            start_query=serializer.validated_data["start"],
            finish_query=serializer.validated_data["finish"],
        )
        return Response(result, status=status.HTTP_200_OK)
