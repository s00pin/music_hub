import uuid
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Album, Artist, Song


class HomePageTests(TestCase):
    def test_home_page_renders_csrf_token_for_ajax_actions(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")


class SearchFallbackTests(TestCase):
    def test_search_uses_local_results_without_external_import(self):
        artist = Artist.objects.create(name="Local Artist")
        album = Album.objects.create(title="Local Album", artist=artist)
        Song.objects.create(title="Local Song", artist=artist, album=album, genre="Rock")

        with patch("music.views.import_musicbrainz_releases") as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Local"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Artist")
        mocked_import.assert_not_called()

    def test_search_fallback_imports_when_local_results_are_empty(self):
        mbid_artist = uuid.uuid4()
        mbid_album = uuid.uuid4()
        mbid_song = uuid.uuid4()

        def fake_importer(query):
            artist = Artist.objects.create(name="Imported Artist", mbid=mbid_artist)
            album = Album.objects.create(title="Imported Album", artist=artist, mbid=mbid_album)
            Song.objects.create(
                title="Imported Track",
                artist=artist,
                album=album,
                genre="Unknown",
                mbid=mbid_song,
            )
            return {
                "attempted": True,
                "artists_created": 1,
                "albums_created": 1,
                "songs_created": 1,
                "created_total": 3,
                "errors": [],
            }

        with patch("music.views.import_musicbrainz_releases", side_effect=fake_importer) as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Imported"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imported Artist")
        self.assertContains(response, "Imported Album")
        self.assertContains(response, "Imported Track")
        self.assertContains(response, "No local matches were found")
        mocked_import.assert_called_once_with("Imported")


class MBIDConstraintTests(TestCase):
    def test_artist_mbid_is_unique(self):
        shared_mbid = uuid.uuid4()
        Artist.objects.create(name="Artist One", mbid=shared_mbid)

        with self.assertRaises(IntegrityError):
            Artist.objects.create(name="Artist Two", mbid=shared_mbid)

    def test_album_and_song_mbid_are_unique(self):
        artist = Artist.objects.create(name="Constraint Artist")
        shared_album_mbid = uuid.uuid4()
        shared_song_mbid = uuid.uuid4()

        album = Album.objects.create(title="Album One", artist=artist, mbid=shared_album_mbid)
        Song.objects.create(title="Song One", artist=artist, album=album, genre="Rock", mbid=shared_song_mbid)

        with self.assertRaises(IntegrityError):
            Album.objects.create(title="Album Two", artist=artist, mbid=shared_album_mbid)

        with self.assertRaises(IntegrityError):
            Song.objects.create(title="Song Two", artist=artist, album=album, genre="Rock", mbid=shared_song_mbid)
