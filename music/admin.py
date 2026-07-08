from django.contrib import admin

from .models import Album, Artist, FavoriteSong, LikeSong, MetadataReport, Song


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("name", "mbid", "image_url")
    search_fields = ("name", "mbid")


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "release_date", "mbid")
    search_fields = ("title", "artist__name", "mbid")
    list_filter = ("release_date",)


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "album", "genre", "release_date", "mbid")
    search_fields = ("title", "artist__name", "album__title", "mbid")
    list_filter = ("genre", "release_date")


@admin.register(FavoriteSong)
class FavoriteSongAdmin(admin.ModelAdmin):
    list_display = ("user", "song", "created_at", "session_key")
    search_fields = ("user__username", "song__title", "session_key")


@admin.register(LikeSong)
class LikeSongAdmin(admin.ModelAdmin):
    list_display = ("user", "song", "created_at")
    search_fields = ("user__username", "song__title")


@admin.register(MetadataReport)
class MetadataReportAdmin(admin.ModelAdmin):
    list_display = ("user", "issue_type", "status", "song", "album", "artist", "created_at")
    search_fields = ("user__username", "song__title", "album__title", "artist__name", "details")
    list_filter = ("issue_type", "status", "created_at")
