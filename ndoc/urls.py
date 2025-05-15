"""
URL configuration for ndoc project.

"""

from django.urls import path, include
from django.shortcuts import redirect


urlpatterns = [
    path('', lambda request: redirect('search/', permanent=False)),
    path('search/', include('search.urls')),
    path('docs/', include('docs.urls')), 
]