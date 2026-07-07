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
COVER_ART_ARCHIVE_RELEASE_URL = "https://coverartarchive.org/release/{mbid}"
MUSICBRAINZ_DELAY_SECONDS = 1.1
MUSICBRAINZ_TIMEOUT_SECONDS = 15
MUSICBRAINZ_RESULT_LIMIT = 5
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
    params = urlencode({"fmt": "json", "inc": "artist-credits+recordings+tags"})
    url = f"{MUSICBRAINZ_RELEASE_LOOKUP_URL.format(mbid=release_mbid)}?{params}"
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
    if release_genre == "Unknown":
        release_genre = _pick_genre(release)

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

    if not album.cover:
        cover_url = _extract_cover_url(_cover_art_lookup(release_uuid))
        if cover_url:
            _save_album_cover(album, cover_url)

    return created_counts


def _upsert_artist(artist_uuid, artist_name):
    normalized_name = _truncate((artist_name or "Unknown Artist").strip() or "Unknown Artist", 200)

    if artist_uuid:
        artist, created = _get_or_create_by_mbid(Artist, artist_uuid, {"name": normalized_name})
        if not created and artist.name != normalized_name and artist.name in {"", "Unknown Artist"}:
            artist.name = normalized_name
            artist.save(update_fields=["name"])
        return artist, created

    existing = Artist.objects.filter(name__iexact=normalized_name).first()
    if existing:
        return existing, False

    return Artist.objects.create(name=normalized_name), True


def _upsert_album(release_uuid, artist, title, release_date):
    defaults = {
        "title": title,
        "artist": artist,
        "release_date": release_date,
    }

    album, created = _get_or_create_by_mbid(Album, release_uuid, defaults)
    if created:
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
    genre = _truncate((fallback_genre or "Unknown").strip() or "Unknown", 100)

    defaults = {
        "title": track_title,
        "artist": song_artist,
        "album": album,
        "genre": genre,
        "release_date": release_date,
    }

    if song_uuid:
        song, created = _get_or_create_by_mbid(Song, song_uuid, defaults)
        if created:
            return song, True

        changed_fields = []
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
            song.save(update_fields=changed_fields)
        return song, False

    existing = Song.objects.filter(
        title__iexact=track_title,
        artist=song_artist,
        album=album,
    ).first()
    if existing:
        return existing, False

    return Song.objects.create(**defaults), True


def _get_or_create_by_mbid(model, mbid, defaults):
    for _ in range(3):
        try:
            with transaction.atomic():
                return model.objects.get_or_create(mbid=mbid, defaults=defaults)
        except IntegrityError:
            existing = model.objects.filter(mbid=mbid).first()
            if existing:
                return existing, False
            time.sleep(0.05)

    return model.objects.get_or_create(mbid=mbid, defaults=defaults)


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

    tags = payload.get("tags") or []
    if not tags:
        return "Unknown"

    sorted_tags = sorted(tags, key=lambda item: item.get("count", 0), reverse=True)
    top_name = (sorted_tags[0].get("name") or "").strip()
    return _truncate(top_name or "Unknown", 100)


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
