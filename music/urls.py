from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="home"),
    path("browse/", views.dashboard, name="browse"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("library/", views.library, name="library"),
    path("search/", views.search_results, name="search-results"),
    path("search/suggestions/", views.search_suggestions, name="search-suggestions"),
    path("favorites/", views.favorite_songs, name="favorites"),
    path("songs/<int:pk>/favorite-toggle/", views.toggle_favorite_song, name="toggle-favorite-song"),
    path("songs/<int:pk>/like-toggle/", views.toggle_like_song, name="toggle-like-song"),
    path("reports/create/", views.create_metadata_report, name="create-metadata-report"),
    path("songs/<int:pk>/platform-options/", views.song_platform_options, name="song-platform-options"),

    path("songs/", views.songs, name="songs"),
    path("songs/add/", views.add_song, name="add-song"),
    path("songs/edit/<int:pk>/", views.edit_song, name="edit-song"),
    path("songs/delete/<int:pk>/", views.delete_song, name="delete-song"),
    path("songs/<int:pk>/", views.song_detail, name="song-detail"),

    path("artists/", views.artists, name="artists"),
    path("artists/add/", views.add_artist, name="add-artist"),
    path("artists/edit/<int:pk>/", views.edit_artist, name="edit-artist"),
    path("artists/delete/<int:pk>/", views.delete_artist, name="delete-artist"),
    path("artists/<int:pk>/", views.artist_detail, name="artist-detail"),

    path("albums/", views.albums, name="albums"),
    path("albums/add/", views.add_album, name="add-album"),
    path("albums/edit/<int:pk>/", views.edit_album, name="edit-album"),
    path("albums/delete/<int:pk>/", views.delete_album, name="delete-album"),
    path("albums/<int:pk>/", views.album_detail, name="album-detail"),
]
