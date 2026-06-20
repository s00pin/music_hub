from django.urls import path
from .views import home
from . import views

urlpatterns = [
    path('', home, name='home'),
    path('songs/', views.song_list, name='song-list'),
]