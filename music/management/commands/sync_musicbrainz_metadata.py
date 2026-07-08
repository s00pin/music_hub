from django.core.management.base import BaseCommand
from django.db.models import Q

from music.models import Album, Artist
from music.services import import_musicbrainz_releases


class Command(BaseCommand):
    help = "Backfill catalog metadata from MusicBrainz for existing local records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=2,
            help="Maximum MusicBrainz release results per query (default: 2).",
        )
        parser.add_argument(
            "--max-queries",
            type=int,
            default=0,
            help="Optional cap for total queries (0 means no cap).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Query all artists and albums, not only records missing media.",
        )

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"]), 10))
        max_queries = max(0, int(options["max_queries"]))
        include_all = bool(options["all"])

        if include_all:
            artist_queries = list(
                Artist.objects.order_by("name").values_list("name", flat=True).distinct()
            )
            album_queries = list(
                Album.objects.select_related("artist")
                .order_by("title")
                .values_list("title", "artist__name")
                .distinct()
            )
        else:
            artist_queries = list(
                Artist.objects.filter(Q(image="") | Q(image__isnull=True), image_url="")
                .order_by("name")
                .values_list("name", flat=True)
                .distinct()
            )
            album_queries = list(
                Album.objects.filter(Q(cover="") | Q(cover__isnull=True), cover_url="")
                .select_related("artist")
                .order_by("title")
                .values_list("title", "artist__name")
                .distinct()
            )

        query_queue = []
        seen = set()

        for artist_name in artist_queries:
            key = (artist_name or "").strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            query_queue.append((artist_name.strip(), f"artist:{artist_name.strip()}"))

        for album_title, artist_name in album_queries:
            title = (album_title or "").strip()
            artist = (artist_name or "").strip()
            query = " ".join(part for part in [title, artist] if part).strip()
            key = query.casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            query_queue.append((query, f"album:{title} / artist:{artist}"))

        if max_queries:
            query_queue = query_queue[:max_queries]

        if not query_queue:
            self.stdout.write(self.style.SUCCESS("No metadata backfill queries needed."))
            return

        total_attempted = 0
        total_artists = 0
        total_albums = 0
        total_songs = 0
        total_errors = 0

        for query, label in query_queue:
            self.stdout.write(f"Syncing {label}")
            summary = import_musicbrainz_releases(query, limit=limit)
            if not summary.get("attempted"):
                continue
            total_attempted += 1
            total_artists += int(summary.get("artists_created") or 0)
            total_albums += int(summary.get("albums_created") or 0)
            total_songs += int(summary.get("songs_created") or 0)
            total_errors += len(summary.get("errors") or [])

        # Fallback: if artist image is still missing, reuse first available album artwork.
        artists_backfilled = 0
        for artist in Artist.objects.filter(Q(image="") | Q(image__isnull=True), image_url="").order_by("id"):
            album_with_local_cover = artist.album_set.filter(cover__isnull=False).exclude(cover="").first()
            if album_with_local_cover and album_with_local_cover.cover:
                artist.image = album_with_local_cover.cover.name
                artist.save(update_fields=["image"])
                artists_backfilled += 1
                continue

            album_with_remote_cover = artist.album_set.exclude(cover_url="").first()
            if album_with_remote_cover and album_with_remote_cover.cover_url:
                artist.image_url = album_with_remote_cover.cover_url
                artist.save(update_fields=["image_url"])
                artists_backfilled += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("MusicBrainz metadata sync complete."))
        self.stdout.write(f"Queries attempted: {total_attempted}")
        self.stdout.write(f"Artists created: {total_artists}")
        self.stdout.write(f"Albums created: {total_albums}")
        self.stdout.write(f"Songs created: {total_songs}")
        self.stdout.write(f"Artists image-backfilled: {artists_backfilled}")
        self.stdout.write(f"Errors reported: {total_errors}")
