from django.urls import path
from .views import home
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    path('songs/', views.songs, name='songs'),
    path('songs/add/', views.add_song, name='add-song'),
    path('songs/edit/<int:pk>/', views.edit_song, name='edit-song'),
    path('songs/delete/<int:pk>/', views.delete_song, name='delete-song'),

    path('artists/', views.artists, name='artists'),
    path('albums/', views.albums, name='albums'),
]
