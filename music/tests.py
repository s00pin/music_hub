import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Album, Artist, FavoriteSong, LikeSong, MetadataReport, Song


User = get_user_model()


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Track your catalog")


class SearchFlowTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(username="member-search", password="pass12345")
        self.admin = User.objects.create_user(
            username="admin-search",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )

    def test_search_uses_local_results_without_external_import(self):
        artist = Artist.objects.create(name="Local Artist")
        album = Album.objects.create(title="Local Album", artist=artist)
        Song.objects.create(title="Local Song", artist=artist, album=album, genre="Rock")

        with patch("music.views.import_musicbrainz_releases") as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Local"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Artist")
        mocked_import.assert_not_called()

    def test_search_hides_import_action_for_non_admin(self):
        with patch("music.views.import_musicbrainz_releases") as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Missing"})

        self.assertEqual(response.status_code, 200)
        mocked_import.assert_not_called()
        self.assertNotContains(response, "Try MusicBrainz import")

    def test_search_shows_import_action_for_admin_when_empty(self):
        self.client.login(username="admin-search", password="pass12345")
        with patch("music.views.import_musicbrainz_releases") as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Missing"})

        self.assertEqual(response.status_code, 200)
        mocked_import.assert_not_called()
        self.assertContains(response, "Try MusicBrainz import")

    def test_search_import_does_not_run_for_non_admin(self):
        self.client.login(username="member-search", password="pass12345")
        with patch("music.views.import_musicbrainz_releases") as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Imported", "import": "1"})

        self.assertEqual(response.status_code, 200)
        mocked_import.assert_not_called()

    def test_search_import_runs_when_requested(self):
        mbid_artist = uuid.uuid4()
        mbid_album = uuid.uuid4()
        mbid_song = uuid.uuid4()

        def fake_importer(query, limit=2):
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

        self.client.login(username="admin-search", password="pass12345")
        with patch("music.views.import_musicbrainz_releases", side_effect=fake_importer) as mocked_import:
            response = self.client.get(reverse("search-results"), {"q": "Imported", "import": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imported Artist")
        self.assertContains(response, "Imported Album")
        self.assertContains(response, "Imported Track")
        mocked_import.assert_called_once()


class FavoriteAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="demo", password="pass12345")
        self.artist = Artist.objects.create(name="A")
        self.album = Album.objects.create(title="B", artist=self.artist)
        self.song = Song.objects.create(title="C", artist=self.artist, album=self.album, genre="Rock")

    def test_toggle_favorite_requires_authentication(self):
        response = self.client.post(reverse("toggle-favorite-song", args=[self.song.id]))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["requires_login"], True)

    def test_toggle_favorite_for_authenticated_user(self):
        self.client.login(username="demo", password="pass12345")
        response = self.client.post(reverse("toggle-favorite-song", args=[self.song.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["is_favorite"], True)
        self.assertTrue(FavoriteSong.objects.filter(user=self.user, song=self.song).exists())

    def test_favorites_page_requires_authentication(self):
        response = self.client.get(reverse("favorites"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class ProtectedViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="member", password="pass12345")
        self.admin = User.objects.create_user(
            username="adminuser",
            password="pass12345",
            is_staff=True,
            is_superuser=True,
        )

    def test_add_song_requires_authentication(self):
        response = self.client.get(reverse("add-song"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_add_song_blocks_non_admin_user(self):
        self.client.login(username="member", password="pass12345")
        response = self.client.get(reverse("add-song"))
        self.assertEqual(response.status_code, 403)

    def test_add_song_allows_admin_user(self):
        self.client.login(username="adminuser", password="pass12345")
        response = self.client.get(reverse("add-song"))
        self.assertEqual(response.status_code, 200)


class LikeAndReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="demo", password="pass12345")
        self.artist = Artist.objects.create(name="A")
        self.album = Album.objects.create(title="B", artist=self.artist)
        self.song = Song.objects.create(title="C", artist=self.artist, album=self.album, genre="Rock")

    def test_toggle_like_requires_authentication(self):
        response = self.client.post(reverse("toggle-like-song", args=[self.song.id]))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["requires_login"], True)

    def test_toggle_like_for_authenticated_user(self):
        self.client.login(username="demo", password="pass12345")
        response = self.client.post(reverse("toggle-like-song", args=[self.song.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["is_liked"], True)
        self.assertTrue(LikeSong.objects.filter(user=self.user, song=self.song).exists())

    def test_report_requires_authentication(self):
        response = self.client.post(
            reverse("create-metadata-report"),
            {"target_kind": "song", "target_id": self.song.id, "issue_type": "incomplete", "details": ""},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["requires_login"], True)

    def test_report_creation_for_authenticated_user(self):
        self.client.login(username="demo", password="pass12345")
        response = self.client.post(
            reverse("create-metadata-report"),
            {
                "target_kind": "song",
                "target_id": self.song.id,
                "issue_type": "false_info",
                "details": "Artist name mismatch",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertTrue(
            MetadataReport.objects.filter(
                user=self.user,
                song=self.song,
                issue_type=MetadataReport.ISSUE_FALSE_INFO,
            ).exists()
        )

    def test_report_rejects_invalid_target(self):
        self.client.login(username="demo", password="pass12345")
        response = self.client.post(
            reverse("create-metadata-report"),
            {
                "target_kind": "playlist",
                "target_id": self.song.id,
                "issue_type": "false_info",
                "details": "Wrong target",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["ok"], False)
        self.assertIn("errors", response.json())

    def test_metadata_report_model_requires_single_target(self):
        report = MetadataReport(
            user=self.user,
            issue_type=MetadataReport.ISSUE_INCOMPLETE,
            song=self.song,
            album=self.album,
        )
        with self.assertRaises(ValidationError):
            report.full_clean()


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
            with transaction.atomic():
                Album.objects.create(title="Album Two", artist=artist, mbid=shared_album_mbid)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Song.objects.create(title="Song Two", artist=artist, album=album, genre="Rock", mbid=shared_song_mbid)
