from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from music.models import Album, Artist, Song


class Command(BaseCommand):
    help = "Populate the database with test and real artists/albums/songs."

    @transaction.atomic
    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)

        def maybe_media_path(relative_path):
            file_path = media_root / relative_path
            return relative_path if file_path.exists() else None

        artist_specs = [
            {"name": "Kendrick Lamar"},
            {"name": "Taylor Swift"},
            {"name": "The Weeknd"},
            {"name": "Daft Punk"},
            {"name": "Billie Eilish"},
            {"name": "Radiohead"},
            {"name": "KennyHoopla", "image": maybe_media_path("artists/kennyhoopla.webp")},
            {"name": "Test Artist Alpha", "image": maybe_media_path("artists/test.jpg")},
            {"name": "Test Artist Beta", "image": maybe_media_path("artists/images.webp")},
        ]

        artist_map = {}
        artist_created = 0

        for spec in artist_specs:
            artist, created = Artist.objects.get_or_create(name=spec["name"])
            if created:
                artist_created += 1
            image_path = spec.get("image")
            if image_path and not artist.image:
                artist.image = image_path
                artist.save(update_fields=["image"])
            artist_map[artist.name] = artist

        album_specs = [
            {
                "title": "DAMN.",
                "artist": "Kendrick Lamar",
                "release_date": date(2017, 4, 14),
            },
            {
                "title": "1989",
                "artist": "Taylor Swift",
                "release_date": date(2014, 10, 27),
            },
            {
                "title": "After Hours",
                "artist": "The Weeknd",
                "release_date": date(2020, 3, 20),
            },
            {
                "title": "Discovery",
                "artist": "Daft Punk",
                "release_date": date(2001, 3, 12),
            },
            {
                "title": "Happier Than Ever",
                "artist": "Billie Eilish",
                "release_date": date(2021, 7, 30),
            },
            {
                "title": "OK Computer",
                "artist": "Radiohead",
                "release_date": date(1997, 5, 21),
            },
            {
                "title": "SURVIVORS GUILT: THE MIXTAPE",
                "artist": "KennyHoopla",
                "release_date": date(2021, 6, 11),
                "cover": maybe_media_path("albums/kennyhooplaalbumcover1.jpeg"),
            },
            {
                "title": "Test Album One",
                "artist": "Test Artist Alpha",
                "release_date": date(2023, 5, 10),
                "cover": maybe_media_path("albums/test.jpg"),
            },
            {
                "title": "Test Album Two",
                "artist": "Test Artist Beta",
                "release_date": date(2024, 2, 1),
                "cover": maybe_media_path("albums/download.jpeg"),
            },
        ]

        album_map = {}
        album_created = 0

        for spec in album_specs:
            artist = artist_map[spec["artist"]]
            album, created = Album.objects.get_or_create(
                title=spec["title"],
                artist=artist,
                defaults={"release_date": spec.get("release_date")},
            )
            if created:
                album_created += 1

            updated = False
            if spec.get("release_date") and album.release_date != spec["release_date"]:
                album.release_date = spec["release_date"]
                updated = True

            cover_path = spec.get("cover")
            if cover_path and not album.cover:
                album.cover = cover_path
                updated = True

            if updated:
                album.save()

            album_map[(album.title, album.artist.name)] = album

        song_specs = [
            {
                "title": "HUMBLE.",
                "artist": "Kendrick Lamar",
                "album": "DAMN.",
                "genre": "Hip-Hop",
                "youtube_link": "https://www.youtube.com/watch?v=tvTRZJ-4EyI",
                "release_date": date(2017, 3, 30),
            },
            {
                "title": "LOVE.",
                "artist": "Kendrick Lamar",
                "album": "DAMN.",
                "genre": "Hip-Hop",
                "youtube_link": "https://www.youtube.com/watch?v=ox7RsX1Ee34",
                "release_date": date(2017, 4, 14),
            },
            {
                "title": "Blank Space",
                "artist": "Taylor Swift",
                "album": "1989",
                "genre": "Pop",
                "youtube_link": "https://www.youtube.com/watch?v=e-ORhEE9VVg",
                "release_date": date(2014, 11, 10),
            },
            {
                "title": "Style",
                "artist": "Taylor Swift",
                "album": "1989",
                "genre": "Pop",
                "youtube_link": "https://www.youtube.com/watch?v=-CmadmM5cOk",
                "release_date": date(2015, 2, 9),
            },
            {
                "title": "Blinding Lights",
                "artist": "The Weeknd",
                "album": "After Hours",
                "genre": "Synthwave",
                "youtube_link": "https://www.youtube.com/watch?v=4NRXx6U8ABQ",
                "release_date": date(2019, 11, 29),
            },
            {
                "title": "Save Your Tears",
                "artist": "The Weeknd",
                "album": "After Hours",
                "genre": "Pop",
                "youtube_link": "https://www.youtube.com/watch?v=XXYlFuWEuKI",
                "release_date": date(2020, 3, 20),
            },
            {
                "title": "One More Time",
                "artist": "Daft Punk",
                "album": "Discovery",
                "genre": "Electronic",
                "youtube_link": "https://www.youtube.com/watch?v=FGBhQbmPwH8",
                "release_date": date(2000, 11, 30),
            },
            {
                "title": "Harder, Better, Faster, Stronger",
                "artist": "Daft Punk",
                "album": "Discovery",
                "genre": "Electronic",
                "youtube_link": "https://www.youtube.com/watch?v=gAjR4_CbPpQ",
                "release_date": date(2001, 10, 13),
            },
            {
                "title": "Therefore I Am",
                "artist": "Billie Eilish",
                "album": "Happier Than Ever",
                "genre": "Alt Pop",
                "youtube_link": "https://www.youtube.com/watch?v=RUQl6YcMalg",
                "release_date": date(2020, 11, 12),
            },
            {
                "title": "Happier Than Ever",
                "artist": "Billie Eilish",
                "album": "Happier Than Ever",
                "genre": "Alt Pop",
                "youtube_link": "https://www.youtube.com/watch?v=5GJWxDKyk3A",
                "release_date": date(2021, 7, 30),
            },
            {
                "title": "Paranoid Android",
                "artist": "Radiohead",
                "album": "OK Computer",
                "genre": "Alternative",
                "youtube_link": "https://www.youtube.com/watch?v=fHiGbolFFGw",
                "release_date": date(1997, 5, 26),
            },
            {
                "title": "Karma Police",
                "artist": "Radiohead",
                "album": "OK Computer",
                "genre": "Alternative",
                "youtube_link": "https://www.youtube.com/watch?v=1uYWYWPc9HU",
                "release_date": date(1997, 8, 25),
            },
            {
                "title": "hollywood sucks//",
                "artist": "KennyHoopla",
                "album": "SURVIVORS GUILT: THE MIXTAPE",
                "genre": "Alternative",
                "youtube_link": "https://www.youtube.com/watch?v=87GGhXxYwkk",
                "release_date": date(2020, 6, 19),
            },
            {
                "title": "TURN BACK TIME",
                "artist": "KennyHoopla",
                "album": "SURVIVORS GUILT: THE MIXTAPE",
                "genre": "Alternative",
                "youtube_link": "https://www.youtube.com/watch?v=I1D8Qj7sYFU",
                "release_date": date(2021, 6, 11),
            },
            {
                "title": "Test Song Alpha",
                "artist": "Test Artist Alpha",
                "album": "Test Album One",
                "genre": "Test",
                "youtube_link": "",
                "release_date": date(2023, 5, 10),
            },
            {
                "title": "Test Song Beta",
                "artist": "Test Artist Beta",
                "album": "Test Album Two",
                "genre": "Test",
                "youtube_link": "",
                "release_date": date(2024, 2, 1),
            },
        ]

        song_created = 0
        for spec in song_specs:
            artist = artist_map[spec["artist"]]
            album = album_map.get((spec["album"], spec["artist"]))
            _, created = Song.objects.get_or_create(
                title=spec["title"],
                artist=artist,
                defaults={
                    "album": album,
                    "genre": spec["genre"],
                    "youtube_link": spec["youtube_link"],
                    "release_date": spec["release_date"],
                },
            )
            if created:
                song_created += 1

        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(f"Artists created: {artist_created}")
        self.stdout.write(f"Albums created: {album_created}")
        self.stdout.write(f"Songs created: {song_created}")
