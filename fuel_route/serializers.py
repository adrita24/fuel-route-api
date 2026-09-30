"""
DRF Serializers for Route Optimization Endpoint.
"""

from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    """
    Validates origin ('start') and destination ('finish') location queries.
    """
    start = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
        error_messages={
            'required': 'Parameter "start" is required.',
            'blank': 'Parameter "start" cannot be empty.',
            'max_length': 'Parameter "start" cannot exceed 255 characters.'
        }
    )
    finish = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=255,
        error_messages={
            'required': 'Parameter "finish" is required.',
            'blank': 'Parameter "finish" cannot be empty.',
            'max_length': 'Parameter "finish" cannot exceed 255 characters.'
        }
    )
