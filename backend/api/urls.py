from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, UploadFileView

router = DefaultRouter()
router.register(r'products', ProductViewSet)

urlpatterns = [
    path('upload/', UploadFileView.as_view(), name='file-upload'),
    path('', include(router.urls)),
]
