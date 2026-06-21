from django.urls import path
from .views import home
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('songs/', views.songs, name='songs'),
    path('artists/', views.artists, name='artists'),
    path('albums/', views.albums, name='albums'),
]