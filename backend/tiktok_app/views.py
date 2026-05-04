from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from platforms.tiktok.service import fetch_tiktok_profile


@api_view(["GET"])
def profile(request, username):
    username = username.lstrip("@")
    try:
        data = fetch_tiktok_profile(username)
        return Response(data)
    except ValueError as e:
        return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"detail": f"Ошибка: {type(e).__name__}: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
