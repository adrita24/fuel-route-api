"""
Custom Exception Handler for Django REST Framework.
Formats all service and validation exceptions into the uniform schema:
  {
    "error": {
      "code": "<ERROR_CODE>",
      "message": "<Error description>"
    }
  }
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from fuel_route.services.exceptions import ServiceException


def custom_exception_handler(exc, context):
    """
    Standardize all exception responses to {"error": {"code": ..., "message": ...}}.
    """
    # 1. Custom Service Exceptions (from geocoding, routing, stations, optimizer)
    if isinstance(exc, ServiceException):
        return Response(
            {
                "error": {
                    "code": exc.error_code,
                    "message": exc.message
                }
            },
            status=exc.http_status
        )

    # 2. Delegate to DRF's default exception handler
    response = exception_handler(exc, context)

    if response is not None:
        # Extract meaningful message from DRF validation error
        data = response.data
        if isinstance(data, dict):
            # Take the first validation field error message
            first_key, first_val = next(iter(data.items()))
            if isinstance(first_val, list) and first_val:
                msg = str(first_val[0])
            else:
                msg = f"{first_key}: {first_val}"
            err_code = "MISSING_INPUT" if response.status_code == status.HTTP_400_BAD_REQUEST else "SERVICE_ERROR"
        elif isinstance(data, list) and data:
            msg = str(data[0])
            err_code = "MISSING_INPUT"
        else:
            msg = str(data)
            err_code = "SERVICE_ERROR"

        return Response(
            {
                "error": {
                    "code": err_code,
                    "message": msg
                }
            },
            status=response.status_code
        )

    return None
