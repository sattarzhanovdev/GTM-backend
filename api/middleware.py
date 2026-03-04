from __future__ import annotations

from django.http import HttpResponse


class SimpleCorsMiddleware:
    """
    Простой CORS для разработки без внешних зависимостей.

    Важно: CORS нужен только для запросов из браузера (например Expo Web).
    Для нативного приложения (iOS/Android) CORS не применяется.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            if request.method == "OPTIONS":
                response = HttpResponse(status=204)
            else:
                response = self.get_response(request)

            origin = request.headers.get("Origin") or "*"
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Max-Age"] = "86400"
            return response

        return self.get_response(request)

