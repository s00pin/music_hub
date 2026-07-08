import json
import logging
import mimetypes
import os
import threading
import time
import uuid
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from music.models import Album, Artist, Song


LOGGER = logging.getLogger(__name__)

MUSICBRAINZ_RELEASE_SEARCH_URL = "https://musicbrainz.org/ws/2/release/"
MUSICBRAINZ_RELEASE_LOOKUP_URL = "https://musicbrainz.org/ws/2/release/{mbid}"
MUSICBRAINZ_RELEASE_GROUP_LOOKUP_URL = "https://musicbrainz.org/ws/2/release-group/{mbid}"
COVER_ART_ARCHIVE_RELEASE_URL = "https://coverartarchive.org/release/{mbid}"
MUSICBRAINZ_DELAY_SECONDS = 1.1
MUSICBRAINZ_TIMEOUT_SECONDS = 15
MUSICBRAINZ_RESULT_LIMIT = 2
DEFAULT_MUSICBRAINZ_USER_AGENT = (
    "music-hub-metadata-cache/2026.07 "
    "(https://music.swop-nil.com; admin@music.swop-nil.com)"
)

_musicbrainz_lock = threading.Lock()


def import_musicbrainz_releases(query, limit=MUSICBRAINZ_RESULT_LIMIT):
    normalized_query = (query or "").strip()
    summary = {
        "attempted": False,
        "artists_created": 0,
        "albums_created": 0,
        "songs_created": 0,
        "created_total": 0,
        "errors": [],
    }

    if not normalized_query:
        return summary

    summary["attempted"] = True
    payload = _musicbrainz_release_search(normalized_query, limit=limit)

    if not payload:
        summary["errors"].append("MusicBrainz lookup returned no payload.")
        return summary

    releases = payload.get("releases") or []
    for release in releases:
        try:
            created = _upsert_release(release)
        except Exception as exc:
            LOGGER.exception("MusicBrainz release import failed for query=%s", normalized_query)
            summary["errors"].append(str(exc))
            continue

        summary["artists_created"] += created["artists"]
        summary["albums_created"] += created["albums"]
        summary["songs_created"] += created["songs"]

    summary["created_total"] = (
        summary["artists_created"] + summary["albums_created"] + summary["songs_created"]
    )
    return summary


def import_musicbrainz_release_payloads(releases):
    summary = {
        "attempted": True,
        "artists_created": 0,
        "albums_created": 0,
        "songs_created": 0,
        "created_total": 0,
        "errors": [],
    }

    for release in releases or []:
        try:
            created = _upsert_release(release)
        except Exception as exc:
            LOGGER.exception("MusicBrainz release payload import failed")
            summary["errors"].append(str(exc))
            continue

        summary["artists_created"] += created["artists"]
        summary["albums_created"] += created["albums"]
        summary["songs_created"] += created["songs"]

    summary["created_total"] = (
        summary["artists_created"] + summary["albums_created"] + summary["songs_created"]
    )
    return summary


def _musicbrainz_release_search(query, limit):
    params = urlencode(
        {
            "query": query,
            "fmt": "json",
            "limit": max(1, min(int(limit or MUSICBRAINZ_RESULT_LIMIT), 10)),
        }
    )
    url = f"{MUSICBRAINZ_RELEASE_SEARCH_URL}?{params}"
    return _request_json(url, throttle_musicbrainz=True)


def _musicbrainz_release_lookup(release_mbid):
    params = urlencode({"fmt": "json", "inc": "artist-credits+recordings+tags+genres+release-groups"})
    url = f"{MUSICBRAINZ_RELEASE_LOOKUP_URL.format(mbid=release_mbid)}?{params}"
    return _request_json(url, throttle_musicbrainz=True)


def _musicbrainz_release_group_lookup(release_group_mbid):
    params = urlencode({"fmt": "json", "inc": "tags+genres"})
    url = f"{MUSICBRAINZ_RELEASE_GROUP_LOOKUP_URL.format(mbid=release_group_mbid)}?{params}"
    return _request_json(url, throttle_musicbrainz=True)


def _cover_art_lookup(release_mbid):
    url = COVER_ART_ARCHIVE_RELEASE_URL.format(mbid=release_mbid)
    return _request_json(url, throttle_musicbrainz=False)


def _request_json(url, throttle_musicbrainz):
    data, _ = _request_bytes(url, throttle_musicbrainz=throttle_musicbrainz)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Could not decode JSON from %s", url)
        return None


def _request_bytes(url, throttle_musicbrainz):
    if throttle_musicbrainz:
        _throttle_musicbrainz()

    headers = {
        "User-Agent": getattr(settings, "MUSICBRAINZ_USER_AGENT", DEFAULT_MUSICBRAINZ_USER_AGENT),
        "Accept": "application/json, image/*;q=0.9, */*;q=0.8",
    }
    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=MUSICBRAINZ_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read()
            return payload, content_type
    except (HTTPError, URLError, TimeoutError) as exc:
        LOGGER.warning("HTTP call failed for %s: %s", url, exc)
        return None, None


def _throttle_musicbrainz():
    with _musicbrainz_lock:
        # Explicitly sleep before every MusicBrainz endpoint call.
        time.sleep(MUSICBRAINZ_DELAY_SECONDS)


def _upsert_release(release):
    release_uuid = _to_uuid(release.get("id"))
    if not release_uuid:
        return {"artists": 0, "albums": 0, "songs": 0}

    artist_mbid, artist_name = _extract_release_artist(release)
    artist_uuid = _to_uuid(artist_mbid)
    release_date = _parse_release_date(release.get("date"))
    release_title = _truncate((release.get("title") or "").strip() or "Untitled Release", 200)
    release_details = _musicbrainz_release_lookup(release_uuid)
    release_tracks = _extract_tracks(release_details)
    release_genre = _pick_genre(release_details)
    if _is_unknown_genre(release_genre):
        release_genre = _pick_genre(release)
    if _is_unknown_genre(release_genre):
        release_group_uuid = _extract_release_group_uuid(release_details or release)
        if release_group_uuid:
            release_group_details = _musicbrainz_release_group_lookup(release_group_uuid)
            release_genre = _pick_genre(release_group_details)

    created_counts = {"artists": 0, "albums": 0, "songs": 0}

    with transaction.atomic():
        artist, created_artist = _upsert_artist(artist_uuid, artist_name)
        album, created_album = _upsert_album(
            release_uuid=release_uuid,
            artist=artist,
            title=release_title,
            release_date=release_date,
        )

        if created_artist:
            created_counts["artists"] += 1
        if created_album:
            created_counts["albums"] += 1

        for track in release_tracks:
            song, created_song = _upsert_song(
                track=track,
                default_artist=artist,
                album=album,
                release_date=release_date,
                fallback_genre=release_genre,
            )
            if created_song:
                created_counts["songs"] += 1

    cover_url = _extract_cover_url(_cover_art_lookup(release_uuid))
    if cover_url and album.cover_url != cover_url:
        album.cover_url = cover_url
        album.save(update_fields=["cover_url"])

    if cover_url and not album.cover:
        _save_album_cover(album, cover_url)

    return created_counts


def _upsert_artist(artist_uuid, artist_name):
    normalized_name = _truncate((artist_name or "Unknown Artist").strip() or "Unknown Artist", 200)

    if artist_uuid:
        artist = Artist.objects.filter(mbid=artist_uuid).first()
        if artist:
            changed_fields = []
            if artist.name != normalized_name and artist.name in {"", "Unknown Artist"}:
                artist.name = normalized_name
                changed_fields.append("name")
            if changed_fields:
                artist.save(update_fields=changed_fields)
            return artist, False

        # Merge into an existing local artist without MBID instead of creating duplicates.
        existing_by_name = Artist.objects.filter(name__iexact=normalized_name).first()
        if existing_by_name:
            changed_fields = []
            if not existing_by_name.mbid:
                existing_by_name.mbid = artist_uuid
                changed_fields.append("mbid")
            if existing_by_name.name != normalized_name and existing_by_name.name in {"", "Unknown Artist"}:
                existing_by_name.name = normalized_name
                changed_fields.append("name")
            if changed_fields:
                try:
                    existing_by_name.save(update_fields=changed_fields)
                except IntegrityError:
                    linked = Artist.objects.filter(mbid=artist_uuid).first()
                    if linked:
                        return linked, False
            return existing_by_name, False

        return Artist.objects.create(name=normalized_name, mbid=artist_uuid), True

    existing = Artist.objects.filter(name__iexact=normalized_name).first()
    if existing:
        return existing, False

    return Artist.objects.create(name=normalized_name), True


def _upsert_album(release_uuid, artist, title, release_date):
    album = Album.objects.filter(mbid=release_uuid).first()
    if not album:
        # Merge into an existing local album with same title/artist to avoid duplicates.
        album = Album.objects.filter(artist=artist, title__iexact=title).first()
        if album:
            changed_fields = []
            if not album.mbid:
                album.mbid = release_uuid
                changed_fields.append("mbid")
            if release_date and album.release_date != release_date:
                album.release_date = release_date
                changed_fields.append("release_date")
            if changed_fields:
                try:
                    album.save(update_fields=changed_fields)
                except IntegrityError:
                    linked = Album.objects.filter(mbid=release_uuid).first()
                    if linked:
                        album = linked
            return album, False

        album = Album.objects.create(
            mbid=release_uuid,
            title=title,
            artist=artist,
            release_date=release_date,
            cover_url="",
        )
        return album, True

    changed_fields = []
    if album.title != title:
        album.title = title
        changed_fields.append("title")
    if album.artist_id != artist.id:
        album.artist = artist
        changed_fields.append("artist")
    if release_date and album.release_date != release_date:
        album.release_date = release_date
        changed_fields.append("release_date")

    if changed_fields:
        album.save(update_fields=changed_fields)

    return album, False


def _upsert_song(track, default_artist, album, release_date, fallback_genre):
    track_title = _truncate((track.get("title") or "").strip() or "Untitled Track", 200)
    track_uuid = _to_uuid(track.get("id"))
    recording_uuid = _to_uuid((track.get("recording") or {}).get("id"))
    song_uuid = track_uuid or recording_uuid
    song_artist = _resolve_track_artist(track, default_artist)
    track_genre = _pick_genre(track.get("recording") or {})
    genre_candidate = track_genre if not _is_unknown_genre(track_genre) else fallback_genre
    if _is_unknown_genre(genre_candidate):
        artist_fallback_genre = _existing_artist_genre(song_artist)
        if artist_fallback_genre:
            genre_candidate = artist_fallback_genre
    genre = _truncate((genre_candidate or "Unknown").strip() or "Unknown", 100)

    defaults = {
        "title": track_title,
        "artist": song_artist,
        "album": album,
        "genre": genre,
        "release_date": release_date,
    }

    song = Song.objects.filter(mbid=song_uuid).first() if song_uuid else None
    if not song:
        song = Song.objects.filter(
            title__iexact=track_title,
            artist=song_artist,
            album=album,
        ).first()

    if song:
        changed_fields = []
        if song_uuid and not song.mbid:
            song.mbid = song_uuid
            changed_fields.append("mbid")
        if song.title != track_title:
            song.title = track_title
            changed_fields.append("title")
        if song.artist_id != song_artist.id:
            song.artist = song_artist
            changed_fields.append("artist")
        if song.album_id != album.id:
            song.album = album
            changed_fields.append("album")
        if song.genre != genre:
            song.genre = genre
            changed_fields.append("genre")
        if release_date and song.release_date != release_date:
            song.release_date = release_date
            changed_fields.append("release_date")

        if changed_fields:
            try:
                song.save(update_fields=changed_fields)
            except IntegrityError:
                if song_uuid:
                    linked = Song.objects.filter(mbid=song_uuid).first()
                    if linked:
                        return linked, False
        return song, False

    existing = Song.objects.filter(
        title__iexact=track_title,
        artist=song_artist,
        album=album,
    ).first()
    if existing:
        return existing, False

    if song_uuid:
        defaults["mbid"] = song_uuid
    return Song.objects.create(**defaults), True

def _extract_release_artist(release):
    for entry in release.get("artist-credit") or []:
        artist_obj = entry.get("artist")
        if artist_obj:
            return artist_obj.get("id"), artist_obj.get("name") or entry.get("name")
        if entry.get("name"):
            return None, entry["name"]
    return None, "Unknown Artist"


def _resolve_track_artist(track, default_artist):
    recording = track.get("recording") or {}
    for entry in recording.get("artist-credit") or []:
        artist_obj = entry.get("artist")
        if artist_obj:
            artist_uuid = _to_uuid(artist_obj.get("id"))
            return _upsert_artist(artist_uuid, artist_obj.get("name"))[0]
        if entry.get("name"):
            return _upsert_artist(None, entry["name"])[0]
    return default_artist


def _extract_tracks(release_payload):
    if not release_payload:
        return []

    tracks = []
    for media in release_payload.get("media") or []:
        tracks.extend(media.get("tracks") or [])
    return tracks


def _pick_genre(payload):
    if not payload:
        return "Unknown"

    genres = payload.get("genres") or []
    if genres:
        sorted_genres = sorted(genres, key=lambda item: item.get("count", 0), reverse=True)
        top_genre = (sorted_genres[0].get("name") or "").strip()
        if top_genre:
            return _truncate(top_genre, 100)

    tags = payload.get("tags") or []
    if not tags:
        return "Unknown"
    sorted_tags = sorted(tags, key=lambda item: item.get("count", 0), reverse=True)
    top_name = (sorted_tags[0].get("name") or "").strip()
    return _truncate(top_name or "Unknown", 100)


def _extract_release_group_uuid(payload):
    if not payload:
        return None

    release_group = payload.get("release-group") or {}
    return _to_uuid(release_group.get("id"))


def _existing_artist_genre(artist):
    if not artist:
        return ""

    known_genres = (
        Song.objects.filter(artist=artist)
        .exclude(genre__isnull=True)
        .exclude(genre__exact="")
        .exclude(genre__iexact="unknown")
        .exclude(genre__iexact="test")
        .values_list("genre", flat=True)
    )
    for genre in known_genres:
        cleaned = (genre or "").strip()
        if cleaned:
            return cleaned
    return ""


def _is_unknown_genre(value):
    return (value or "").strip().casefold() in {"", "unknown", "test"}


def _extract_cover_url(payload):
    if not payload:
        return None

    for image in payload.get("images") or []:
        if not image.get("front"):
            continue
        thumbnails = image.get("thumbnails") or {}
        return thumbnails.get("large") or thumbnails.get("small") or image.get("image")
    return None


def _save_album_cover(album, cover_url):
    image_data, content_type = _request_bytes(cover_url, throttle_musicbrainz=False)
    if not image_data:
        return

    extension = _guess_extension(cover_url, content_type)
    file_stem = str(album.mbid or slugify(album.title) or album.pk)
    file_name = f"{file_stem[:120]}-cover{extension}"
    album.cover.save(file_name, ContentFile(image_data), save=False)
    album.save(update_fields=["cover"])


def _guess_extension(url, content_type):
    parsed_path = urlparse(url).path
    extension = os.path.splitext(parsed_path)[1].lower()
    if extension in {".jpg", ".jpeg", ".png", ".webp"}:
        return extension

    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed in {".jpg", ".jpeg", ".png", ".webp"}:
        return guessed
    return ".jpg"


def _parse_release_date(value):
    if not value:
        return None

    text = str(value).strip()
    if len(text) == 10:
        try:
            year, month, day = text.split("-")
            return date(int(year), int(month), int(day))
        except ValueError:
            return None
    if len(text) == 7:
        try:
            year, month = text.split("-")
            return date(int(year), int(month), 1)
        except ValueError:
            return None
    if len(text) == 4:
        try:
            return date(int(text), 1, 1)
        except ValueError:
            return None
    return None


def _to_uuid(raw_value):
    if not raw_value:
        return None
    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return None


def _truncate(value, length):
    text = str(value or "")
    if len(text) <= length:
        return text
    return text[:length]
