from urllib.parse import quote_plus, urlencode
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import AlbumForm, ArtistForm, MetadataReportForm, SongForm
from .models import Album, Artist, FavoriteSong, LikeSong, Song
from .services import import_musicbrainz_releases


ARTIST_PLACEHOLDER = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 800'%3E"
    "%3Crect width='800' height='800' fill='%23f1f3f7'/%3E"
    "%3Ccircle cx='400' cy='300' r='150' fill='%23c7ceda'/%3E"
    "%3Crect x='180' y='500' width='440' height='200' rx='90' fill='%23c7ceda'/%3E"
    "%3C/svg%3E"
)
ALBUM_PLACEHOLDER = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 800'%3E"
    "%3Crect width='800' height='800' fill='%23f1f3f7'/%3E"
    "%3Crect x='140' y='140' width='520' height='520' fill='%23c7ceda'/%3E"
    "%3Ccircle cx='400' cy='400' r='120' fill='%23f1f3f7'/%3E"
    "%3Ccircle cx='400' cy='400' r='26' fill='%23c7ceda'/%3E"
    "%3C/svg%3E"
)
LIST_PAGE_SIZE = 50
PER_PAGE_OPTIONS = [10, 50, 100, 200, 500, 1000]
UNKNOWN_GENRE_VALUES = {
    "unknown",
    "unknown genre",
    "unk",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "other",
    "misc",
    "miscellaneous",
    "-",
    "?",
    "unclassified",
    "not set",
}


def _is_unknown_genre(raw_value):
    normalized = (raw_value or "").strip().casefold()
    if not normalized:
        return False
    if normalized in UNKNOWN_GENRE_VALUES:
        return True
    return "unknown" in normalized


def _genre_label(raw_value):
    label = (raw_value or "").strip()
    if not label:
        return ""
    if _is_unknown_genre(label):
        return "Other"
    return label


def _common_context():
    return {
        "artist_placeholder": ARTIST_PLACEHOLDER,
        "album_placeholder": ALBUM_PLACEHOLDER,
    }


def _search_filter_context():
    return {
        "search_genres": _normalized_genre_choices(),
    }


def _user_action_context(request):
    return {
        "favorite_song_ids": _favorite_song_ids(request),
        "liked_song_ids": _like_song_ids(request),
    }


def _query_params(request, remove_keys=None):
    remove = set(remove_keys or [])
    params = []
    for key, values in request.GET.lists():
        if key in remove:
            continue
        for value in values:
            params.append((key, value))
    return params


def _query_prefix(params):
    encoded = urlencode(params, doseq=True)
    return f"{encoded}&" if encoded else ""


def _requested_per_page(request):
    raw_value = (request.GET.get("per_page") or "").strip()
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = LIST_PAGE_SIZE
    return parsed if parsed in PER_PAGE_OPTIONS else LIST_PAGE_SIZE


def _paginate(request, queryset, per_page=LIST_PAGE_SIZE, page_param="page"):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get(page_param))


def _favorite_song_ids(request):
    if not request.user.is_authenticated:
        return set()
    return set(FavoriteSong.objects.filter(user=request.user).values_list("song_id", flat=True))


def _like_song_ids(request):
    if not request.user.is_authenticated:
        return set()
    return set(LikeSong.objects.filter(user=request.user).values_list("song_id", flat=True))


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def _song_platform_links(song, country_code=""):
    query = quote_plus(f"{song.title} {song.artist.name}")
    cc = (country_code or "").upper()

    apple_country = cc.lower() if cc else "us"
    base_links = {
        "youtube": {
            "name": "YouTube",
            "url": song.youtube_link or f"https://www.youtube.com/results?search_query={query}",
        },
        "spotify": {
            "name": "Spotify",
            "url": f"https://open.spotify.com/search/{query}",
        },
        "apple": {
            "name": "Apple Music",
            "url": f"https://music.apple.com/{apple_country}/search?term={query}",
        },
        "deezer": {
            "name": "Deezer",
            "url": f"https://www.deezer.com/search/{query}",
        },
        "soundcloud": {
            "name": "SoundCloud",
            "url": f"https://soundcloud.com/search?q={query}",
        },
    }

    regional = {
        "IN": [
            {"name": "JioSaavn", "url": f"https://www.jiosaavn.com/search/{query}"},
            {"name": "Gaana", "url": f"https://gaana.com/search/{query}"},
            {"name": "Wynk", "url": f"https://wynk.in/music/search/{query}"},
            base_links["youtube"],
            base_links["spotify"],
        ],
        "FR": [base_links["deezer"], base_links["spotify"], base_links["youtube"], base_links["apple"]],
        "DE": [base_links["deezer"], base_links["spotify"], base_links["youtube"], base_links["apple"]],
        "BR": [base_links["deezer"], base_links["spotify"], base_links["youtube"], base_links["apple"]],
        "US": [base_links["spotify"], base_links["apple"], base_links["youtube"], base_links["soundcloud"]],
        "CA": [base_links["spotify"], base_links["apple"], base_links["youtube"], base_links["soundcloud"]],
        "GB": [base_links["spotify"], base_links["apple"], base_links["youtube"], base_links["soundcloud"]],
    }

    ordered = regional.get(
        cc,
        [base_links["spotify"], base_links["youtube"], base_links["apple"], base_links["deezer"], base_links["soundcloud"]],
    )

    unique_links = []
    seen = set()
    for item in ordered:
        key = (item["name"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        unique_links.append(item)

    return unique_links


def _build_search_querysets(query, result_type, selected_genre):
    artists_qs = Artist.objects.all()
    albums_qs = Album.objects.select_related("artist").all()
    songs_qs = Song.objects.select_related("artist", "album").all()

    if query:
        artists_qs = artists_qs.filter(name__icontains=query)
        albums_qs = albums_qs.filter(Q(title__icontains=query) | Q(artist__name__icontains=query))
        songs_qs = songs_qs.filter(
            Q(title__icontains=query)
            | Q(artist__name__icontains=query)
            | Q(album__title__icontains=query)
            | Q(genre__icontains=query)
        )

    if selected_genre:
        if selected_genre.casefold() == "other":
            unknown_filter = Q()
            for value in UNKNOWN_GENRE_VALUES:
                unknown_filter |= Q(genre__iexact=value)
            unknown_filter |= Q(genre__icontains="unknown")
            songs_qs = songs_qs.filter(unknown_filter)
        else:
            songs_qs = songs_qs.filter(genre__iexact=selected_genre)

    artists_qs = artists_qs.order_by("name")
    albums_qs = albums_qs.order_by("title")
    songs_qs = songs_qs.order_by("title")

    if result_type == "artist":
        albums_qs = Album.objects.none()
        songs_qs = Song.objects.none()
    elif result_type == "album":
        artists_qs = Artist.objects.none()
        songs_qs = Song.objects.none()
    elif result_type == "song":
        artists_qs = Artist.objects.none()
        albums_qs = Album.objects.none()

    return artists_qs, albums_qs, songs_qs


def _normalized_genre_choices():
    raw_genres = (
        Song.objects.exclude(genre="")
        .values_list("genre", flat=True)
        .distinct()
        .order_by("genre")
    )

    cleaned = []
    seen = set()
    has_other = False

    for raw_genre in raw_genres:
        label = (raw_genre or "").strip()
        if not label:
            continue

        normalized_key = label.casefold()
        if _is_unknown_genre(label):
            has_other = True
            continue

        if normalized_key in seen:
            continue

        seen.add(normalized_key)
        cleaned.append(label)

    cleaned.sort(key=str.casefold)
    if has_other:
        cleaned.append("Other")

    return cleaned


def _build_personal_playlists(songs_qs, limit=6):
    genre_rows = list(
        songs_qs.exclude(genre="")
        .values("genre")
        .annotate(song_count=Count("id"))
        .order_by("-song_count", "genre")[:limit]
    )

    playlists = [
        {
            "title": f"{row['genre']} Mix",
            "subtitle": f"{row['song_count']} song{'s' if row['song_count'] != 1 else ''}",
        }
        for row in genre_rows
    ]

    if playlists:
        return playlists

    total = songs_qs.count()
    if total:
        return [
            {
                "title": "Saved Tracks",
                "subtitle": f"{total} song{'s' if total != 1 else ''}",
            }
        ]

    return []


def _dashboard_shortcut_genres(limit=12):
    choices = _normalized_genre_choices()
    has_other = "Other" in choices
    if has_other:
        choices = [choice for choice in choices if choice != "Other"]

    if has_other:
        max_without_other = max(limit - 1, 0)
        choices = choices[:max_without_other]
        choices.append("Other")
    else:
        choices = choices[:limit]

    return [{"label": choice, "genre": choice} for choice in choices]


def _dashboard_song_cards(songs):
    return [
        {
            "song": song,
            "genre_label": _genre_label(song.genre),
        }
        for song in songs
    ]


def _dashboard_album_cards(albums):
    cards = []
    for album in albums:
        album_songs = getattr(album, "dashboard_songs", [])
        lead_song = album_songs[0] if album_songs else None
        cards.append(
            {
                "album": album,
                "genre_label": _genre_label(lead_song.genre) if lead_song else "",
                "representative_song_id": lead_song.id if lead_song else None,
            }
        )
    return cards


def _dashboard_artist_cards(artists):
    cards = []
    for artist in artists:
        artist_songs = getattr(artist, "dashboard_songs", [])
        lead_song = artist_songs[0] if artist_songs else None
        cards.append(
            {
                "artist": artist,
                "representative_song_id": lead_song.id if lead_song else None,
            }
        )
    return cards


def _dashboard_featured_song_rows(songs):
    return [
        {
            "song": song,
            "genre_label": _genre_label(song.genre),
        }
        for song in songs
    ]


@ensure_csrf_cookie
def dashboard(request):
    recent_songs = list(Song.objects.select_related("artist", "album").order_by("-id")[:8])
    featured_songs = list(Song.objects.select_related("artist", "album").order_by("-release_date", "title")[:6])
    normalized_genres = _normalized_genre_choices()
    total_songs = Song.objects.count()
    total_artists = Artist.objects.count()
    total_albums = Album.objects.count()
    total_genres = len(normalized_genres)

    dashboard_metrics = [
        {"value": total_songs, "label": "Total Songs"},
        {"value": total_artists, "label": "Total Artists"},
        {"value": total_albums, "label": "Total Albums"},
        {"value": total_genres, "label": "Total Genres"},
    ]
    if request.user.is_authenticated:
        dashboard_metrics.append({"value": len(featured_songs), "label": "Continue Listening"})

    album_song_prefetch = Prefetch(
        "song_set",
        queryset=Song.objects.only("id", "genre", "album_id").order_by("id"),
        to_attr="dashboard_songs",
    )
    featured_albums = list(
        Album.objects.select_related("artist")
        .prefetch_related(album_song_prefetch)
        .order_by("-release_date", "title")[:6]
    )

    artist_song_prefetch = Prefetch(
        "song_set",
        queryset=Song.objects.only("id", "artist_id").order_by("id"),
        to_attr="dashboard_songs",
    )
    featured_artists = list(
        Artist.objects.annotate(song_count=Count("song"))
        .prefetch_related(artist_song_prefetch)
        .order_by("-song_count", "name")[:6]
    )

    context = {
        "featured_songs": featured_songs,
        "featured_song_rows": _dashboard_featured_song_rows(featured_songs),
        "featured_albums": featured_albums,
        "featured_artists": featured_artists,
        "recent_songs": recent_songs,
        "recent_song_cards": _dashboard_song_cards(recent_songs),
        "album_cards": _dashboard_album_cards(featured_albums),
        "artist_cards": _dashboard_artist_cards(featured_artists),
        "dashboard_metrics": dashboard_metrics,
        "shortcut_genres": _dashboard_shortcut_genres(),
        "total_songs": total_songs,
        "total_artists": total_artists,
        "total_albums": total_albums,
        "total_genres": total_genres,
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/dashboard.html", context)


@ensure_csrf_cookie
def home(request):
    return dashboard(request)


@ensure_csrf_cookie
def library(request):
    if request.user.is_authenticated:
        liked_songs_qs = (
            Song.objects.select_related("artist", "album")
            .filter(likes__user=request.user)
            .order_by("title")
            .distinct()
        )
        liked_albums_qs = (
            Album.objects.select_related("artist")
            .filter(song__likes__user=request.user)
            .order_by("title")
            .distinct()
        )
    else:
        liked_songs_qs = Song.objects.none()
        liked_albums_qs = Album.objects.none()

    liked_songs = list(liked_songs_qs[:8])
    liked_albums = list(liked_albums_qs[:8])
    personal_playlists = _build_personal_playlists(liked_songs_qs)

    profile_name = request.user.username if request.user.is_authenticated else "Guest"

    context = {
        "profile_name": profile_name,
        "profile_initial": profile_name[:1].upper() if profile_name else "G",
        "liked_songs": liked_songs,
        "liked_albums": liked_albums,
        "personal_playlists": personal_playlists,
        "liked_song_count": liked_songs_qs.count(),
        "liked_album_count": liked_albums_qs.count(),
        "playlist_count": len(personal_playlists),
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/library.html", context)


@ensure_csrf_cookie
def songs(request):
    per_page = _requested_per_page(request)
    songs_qs = Song.objects.select_related("artist", "album").order_by("title")
    songs_page = _paginate(request, songs_qs, per_page=per_page, page_param="page")
    song_rows = list(songs_page.object_list)
    songs_pagination_params = _query_params(request, remove_keys={"page"})
    songs_per_page_params = _query_params(request, remove_keys={"per_page", "page"})
    return render(
        request,
        "music/songs.html",
        {
            "songs": song_rows,
            "song_cards": _dashboard_song_cards(song_rows),
            "songs_page": songs_page,
            "per_page": per_page,
            "per_page_options": PER_PAGE_OPTIONS,
            "songs_pagination_params": songs_pagination_params,
            "songs_pagination_query": _query_prefix(songs_pagination_params),
            "songs_per_page_params": songs_per_page_params,
            **_user_action_context(request),
            **_common_context(),
        },
    )


@ensure_csrf_cookie
def artists(request):
    per_page = _requested_per_page(request)
    artist_song_prefetch = Prefetch(
        "song_set",
        queryset=Song.objects.only("id", "artist_id").order_by("id"),
        to_attr="dashboard_songs",
    )
    artists_qs = Artist.objects.annotate(
        album_count=Count("album", distinct=True),
        song_count=Count("song", distinct=True),
    ).prefetch_related(artist_song_prefetch).order_by("name")
    artists_page = _paginate(request, artists_qs, per_page=per_page, page_param="page")
    artist_rows = list(artists_page.object_list)
    artists_pagination_params = _query_params(request, remove_keys={"page"})
    artists_per_page_params = _query_params(request, remove_keys={"per_page", "page"})
    return render(
        request,
        "music/artists.html",
        {
            "artists": artist_rows,
            "artist_cards": _dashboard_artist_cards(artist_rows),
            "artists_page": artists_page,
            "per_page": per_page,
            "per_page_options": PER_PAGE_OPTIONS,
            "artists_pagination_params": artists_pagination_params,
            "artists_pagination_query": _query_prefix(artists_pagination_params),
            "artists_per_page_params": artists_per_page_params,
            **_user_action_context(request),
            **_common_context(),
        },
    )


@ensure_csrf_cookie
def albums(request):
    per_page = _requested_per_page(request)
    album_song_prefetch = Prefetch(
        "song_set",
        queryset=Song.objects.only("id", "genre", "album_id").order_by("id"),
        to_attr="dashboard_songs",
    )
    albums_qs = (
        Album.objects.select_related("artist")
        .annotate(song_count=Count("song"))
        .prefetch_related(album_song_prefetch)
        .order_by("title")
    )
    albums_page = _paginate(request, albums_qs, per_page=per_page, page_param="page")
    album_rows = list(albums_page.object_list)
    albums_pagination_params = _query_params(request, remove_keys={"page"})
    albums_per_page_params = _query_params(request, remove_keys={"per_page", "page"})
    return render(
        request,
        "music/albums.html",
        {
            "albums": album_rows,
            "album_cards": _dashboard_album_cards(album_rows),
            "albums_page": albums_page,
            "per_page": per_page,
            "per_page_options": PER_PAGE_OPTIONS,
            "albums_pagination_params": albums_pagination_params,
            "albums_pagination_query": _query_prefix(albums_pagination_params),
            "albums_per_page_params": albums_per_page_params,
            **_user_action_context(request),
            **_common_context(),
        },
    )


@ensure_csrf_cookie
def search_results(request):
    query = request.GET.get("q", "").strip()
    result_type = request.GET.get("type", "all")
    selected_genre = request.GET.get("genre", "").strip()
    import_requested = request.GET.get("import") == "1"
    per_page = _requested_per_page(request)
    can_manage_catalog = request.user.is_authenticated and request.user.is_staff

    artists_qs, albums_qs, songs_qs = _build_search_querysets(
        query=query,
        result_type=result_type,
        selected_genre=selected_genre,
    )

    artist_count = artists_qs.count()
    album_count = albums_qs.count()
    song_count = songs_qs.count()

    external_lookup_summary = {
        "attempted": False,
        "artists_created": 0,
        "albums_created": 0,
        "songs_created": 0,
        "created_total": 0,
        "errors": [],
    }

    allow_auto_import = bool(getattr(settings, "MUSICBRAINZ_AUTO_IMPORT_ON_EMPTY", False))
    should_try_import = (
        can_manage_catalog
        and query
        and artist_count == 0
        and album_count == 0
        and song_count == 0
        and (import_requested or allow_auto_import)
    )

    if should_try_import:
        import_limit = int(getattr(settings, "MUSICBRAINZ_IMPORT_LIMIT", 2))
        external_lookup_summary = import_musicbrainz_releases(query, limit=import_limit)
        if external_lookup_summary.get("created_total"):
            artists_qs, albums_qs, songs_qs = _build_search_querysets(
                query=query,
                result_type=result_type,
                selected_genre=selected_genre,
            )
            artist_count = artists_qs.count()
            album_count = albums_qs.count()
            song_count = songs_qs.count()

    artists_page = _paginate(request, artists_qs, per_page=per_page, page_param="artist_page")
    albums_page = _paginate(request, albums_qs, per_page=per_page, page_param="album_page")
    songs_page = _paginate(request, songs_qs, per_page=per_page, page_param="song_page")

    artists_pagination_params = _query_params(request, remove_keys={"artist_page"})
    albums_pagination_params = _query_params(request, remove_keys={"album_page"})
    songs_pagination_params = _query_params(request, remove_keys={"song_page"})

    context = {
        "query": query,
        "result_type": result_type,
        "selected_genre": selected_genre,
        "artists": artists_page.object_list,
        "albums": albums_page.object_list,
        "songs": songs_page.object_list,
        "artists_page": artists_page,
        "albums_page": albums_page,
        "songs_page": songs_page,
        "per_page": per_page,
        "per_page_options": PER_PAGE_OPTIONS,
        "artists_pagination_params": artists_pagination_params,
        "albums_pagination_params": albums_pagination_params,
        "songs_pagination_params": songs_pagination_params,
        "artists_pagination_query": _query_prefix(artists_pagination_params),
        "albums_pagination_query": _query_prefix(albums_pagination_params),
        "songs_pagination_query": _query_prefix(songs_pagination_params),
        **_user_action_context(request),
        "artist_count": artist_count,
        "album_count": album_count,
        "song_count": song_count,
        "show_import_action": bool(
            can_manage_catalog
            and query
            and artist_count == 0
            and album_count == 0
            and song_count == 0
            and not external_lookup_summary["attempted"]
        ),
        "external_lookup_summary": external_lookup_summary,
        **_search_filter_context(),
        **_common_context(),
    }
    return render(request, "music/search_results.html", context)


def search_suggestions(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"results": []})

    results = []

    for artist in Artist.objects.filter(name__icontains=query).order_by("name")[:4]:
        results.append(
            {
                "type": "Artist",
                "label": artist.name,
                "url": reverse("artist-detail", args=[artist.pk]),
            }
        )

    for album in Album.objects.select_related("artist").filter(
        Q(title__icontains=query) | Q(artist__name__icontains=query)
    ).order_by("title")[:4]:
        results.append(
            {
                "type": "Album",
                "label": f"{album.title} - {album.artist.name}",
                "url": reverse("album-detail", args=[album.pk]),
            }
        )

    for song in Song.objects.select_related("artist").filter(
        Q(title__icontains=query) | Q(artist__name__icontains=query)
    ).order_by("title")[:8]:
        results.append(
            {
                "type": "Song",
                "label": f"{song.title} - {song.artist.name}",
                "url": reverse("song-detail", args=[song.pk]),
            }
        )

    return JsonResponse({"results": results[:12]})


@ensure_csrf_cookie
def artist_detail(request, pk):
    artist = get_object_or_404(Artist, pk=pk)
    album_song_prefetch = Prefetch(
        "song_set",
        queryset=Song.objects.only("id", "genre", "album_id").order_by("id"),
        to_attr="dashboard_songs",
    )
    albums_qs = (
        Album.objects.filter(artist=artist)
        .prefetch_related(album_song_prefetch)
        .order_by("-release_date", "title")
    )
    songs_qs = Song.objects.filter(artist=artist).select_related("album").order_by("title")
    album_rows = list(albums_qs)
    song_rows = list(songs_qs)

    context = {
        "artist": artist,
        "albums": album_rows,
        "songs": song_rows,
        "album_cards": _dashboard_album_cards(album_rows),
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/artist_detail.html", context)


@ensure_csrf_cookie
def album_detail(request, pk):
    album = get_object_or_404(Album.objects.select_related("artist"), pk=pk)
    songs_qs = Song.objects.filter(album=album).select_related("artist").order_by("title")
    song_rows = list(songs_qs)

    context = {
        "album": album,
        "songs": song_rows,
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/album_detail.html", context)


@ensure_csrf_cookie
def song_detail(request, pk):
    song = get_object_or_404(Song.objects.select_related("artist", "album"), pk=pk)
    related_songs_qs = (
        Song.objects.select_related("artist", "album")
        .filter(artist=song.artist)
        .exclude(pk=song.pk)
        .order_by("title")[:6]
    )
    related_songs = list(related_songs_qs)

    context = {
        "song": song,
        "related_songs": related_songs,
        "related_song_cards": _dashboard_song_cards(related_songs),
        "default_platform_links": _song_platform_links(song),
        "is_favorite": song.id in _favorite_song_ids(request),
        "is_liked": song.id in _like_song_ids(request),
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/song_detail.html", context)


def song_platform_options(request, pk):
    song = get_object_or_404(Song.objects.select_related("artist"), pk=pk)
    country = request.GET.get("country", "")
    links = _song_platform_links(song, country_code=country)
    return JsonResponse({"country": country.upper(), "links": links})


@require_POST
def toggle_favorite_song(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "requires_login": True,
                "login_url": reverse("login"),
            },
            status=401,
        )

    song = get_object_or_404(Song, pk=pk)
    favorite, created = FavoriteSong.objects.get_or_create(user=request.user, song=song, defaults={"session_key": None})

    if created:
        return JsonResponse({"ok": True, "is_favorite": True})

    favorite.delete()
    return JsonResponse({"ok": True, "is_favorite": False})


@require_POST
def toggle_like_song(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "requires_login": True,
                "login_url": reverse("login"),
            },
            status=401,
        )

    song = get_object_or_404(Song, pk=pk)
    like, created = LikeSong.objects.get_or_create(user=request.user, song=song)

    if created:
        return JsonResponse({"ok": True, "is_liked": True})

    like.delete()
    return JsonResponse({"ok": True, "is_liked": False})


@require_POST
def create_metadata_report(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "requires_login": True,
                "login_url": reverse("login"),
            },
            status=401,
        )

    form = MetadataReportForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": "Please correct the form and try again.",
                "errors": form.errors.get_json_data(),
            },
            status=400,
        )

    report = form.save_for_user(request.user)
    return JsonResponse({"ok": True, "report_id": report.id})


@login_required
@ensure_csrf_cookie
def favorite_songs(request):
    per_page = _requested_per_page(request)
    songs_qs = (
        Song.objects.select_related("artist", "album")
        .filter(favorites__user=request.user)
        .order_by("title")
        .distinct()
    )
    songs_page = _paginate(request, songs_qs, per_page=per_page, page_param="page")
    favorites_pagination_params = _query_params(request, remove_keys={"page"})
    favorites_per_page_params = _query_params(request, remove_keys={"per_page", "page"})

    context = {
        "songs": songs_page.object_list,
        "songs_page": songs_page,
        "per_page": per_page,
        "per_page_options": PER_PAGE_OPTIONS,
        "favorites_pagination_params": favorites_pagination_params,
        "favorites_pagination_query": _query_prefix(favorites_pagination_params),
        "favorites_per_page_params": favorites_per_page_params,
        **_user_action_context(request),
        **_common_context(),
    }
    return render(request, "music/favorites.html", context)


@admin_required
def add_artist(request):
    if request.method == "POST":
        form = ArtistForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            return redirect("artists")
    else:
        form = ArtistForm()

    return render(
        request,
        "music/artist_form.html",
        {
            "form": form,
            "title": "Add Artist",
            "submit_label": "Save Artist",
            "cancel_url": "artists",
        },
    )


@admin_required
def edit_artist(request, pk):
    artist = get_object_or_404(Artist, pk=pk)

    if request.method == "POST":
        form = ArtistForm(request.POST, request.FILES, instance=artist)

        if form.is_valid():
            form.save()
            return redirect("artists")
    else:
        form = ArtistForm(instance=artist)

    return render(
        request,
        "music/artist_form.html",
        {
            "form": form,
            "title": "Edit Artist",
            "artist": artist,
            "submit_label": "Update Artist",
            "cancel_url": "artists",
        },
    )


@admin_required
def delete_artist(request, pk):
    artist = get_object_or_404(Artist, pk=pk)

    if request.method == "POST":
        artist.delete()
        return redirect("artists")

    return render(request, "music/delete_artist.html", {"artist": artist, "cancel_url": "artists"})


@admin_required
def add_album(request):
    if request.method == "POST":
        form = AlbumForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            return redirect("albums")
    else:
        form = AlbumForm()

    return render(
        request,
        "music/album_form.html",
        {
            "form": form,
            "title": "Add Album",
            "submit_label": "Save Album",
            "cancel_url": "albums",
        },
    )


@admin_required
def edit_album(request, pk):
    album = get_object_or_404(Album, pk=pk)

    if request.method == "POST":
        form = AlbumForm(request.POST, request.FILES, instance=album)

        if form.is_valid():
            form.save()
            return redirect("albums")
    else:
        form = AlbumForm(instance=album)

    return render(
        request,
        "music/album_form.html",
        {
            "form": form,
            "title": "Edit Album",
            "album": album,
            "submit_label": "Update Album",
            "cancel_url": "albums",
        },
    )


@admin_required
def delete_album(request, pk):
    album = get_object_or_404(Album, pk=pk)

    if request.method == "POST":
        album.delete()
        return redirect("albums")

    return render(request, "music/delete_album.html", {"album": album, "cancel_url": "albums"})


@admin_required
def add_song(request):
    if request.method == "POST":
        form = SongForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("songs")
    else:
        form = SongForm()

    return render(
        request,
        "music/song_form.html",
        {
            "form": form,
            "title": "Add Song",
            "submit_label": "Save Song",
            "cancel_url": "songs",
        },
    )


@admin_required
def edit_song(request, pk):
    song = get_object_or_404(Song, pk=pk)

    if request.method == "POST":
        form = SongForm(request.POST, instance=song)

        if form.is_valid():
            form.save()
            return redirect("songs")
    else:
        form = SongForm(instance=song)

    return render(
        request,
        "music/song_form.html",
        {
            "form": form,
            "title": "Edit Song",
            "song": song,
            "submit_label": "Update Song",
            "cancel_url": "songs",
        },
    )


@admin_required
def delete_song(request, pk):
    song = get_object_or_404(Song, pk=pk)

    if request.method == "POST":
        song.delete()
        return redirect("songs")

    return render(request, "music/delete_song.html", {"song": song, "cancel_url": "songs"})


def signup(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = UserCreationForm()

    return render(request, "registration/signup.html", {"form": form})
