from .views import DocsView
from django.urls import re_path

urlpatterns = [
    re_path(r'^(?P<path>.*)$', DocsView.as_view(), name='serve_docs'),
]
