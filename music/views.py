from urllib.parse import quote_plus

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import AlbumForm, ArtistForm, SongForm
from .models import Album, Artist, FavoriteSong, Song


ARTIST_PLACEHOLDER = "/media/artists/test.jpg"
ALBUM_PLACEHOLDER = "/media/albums/blankplaceholder.jpg"


def _common_context():
    return {
        "artist_placeholder": ARTIST_PLACEHOLDER,
        "album_placeholder": ALBUM_PLACEHOLDER,
    }


def _search_filter_context():
    return {
        "search_artists": Artist.objects.order_by("name"),
        "search_albums": Album.objects.select_related("artist").order_by("title"),
        "search_genres": Song.objects.exclude(genre="").values_list("genre", flat=True).distinct().order_by("genre"),
    }


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _favorite_song_ids(request):
    session_key = _ensure_session_key(request)
    return set(FavoriteSong.objects.filter(session_key=session_key).values_list("song_id", flat=True))


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


def home(request):
    context = {
        "featured_songs": Song.objects.select_related("artist", "album").order_by("-release_date", "title")[:6],
        "featured_albums": Album.objects.select_related("artist").order_by("-release_date", "title")[:6],
        "featured_artists": Artist.objects.annotate(song_count=Count("song")).order_by("-song_count", "name")[:6],
        "favorite_song_ids": _favorite_song_ids(request),
        **_search_filter_context(),
        **_common_context(),
    }
    return render(request, "music/home.html", context)


def songs(request):
    songs_qs = Song.objects.select_related("artist", "album").order_by("title")
    return render(
        request,
        "music/songs.html",
        {
            "songs": songs_qs,
            "favorite_song_ids": _favorite_song_ids(request),
            **_common_context(),
        },
    )


def artists(request):
    artists_qs = Artist.objects.annotate(
        album_count=Count("album", distinct=True),
        song_count=Count("song", distinct=True),
    ).order_by("name")
    return render(request, "music/artists.html", {"artists": artists_qs, **_common_context()})


def albums(request):
    albums_qs = Album.objects.select_related("artist").annotate(song_count=Count("song")).order_by("title")
    return render(request, "music/albums.html", {"albums": albums_qs, **_common_context()})


def search_results(request):
    query = request.GET.get("q", "").strip()
    result_type = request.GET.get("type", "all")
    selected_genre = request.GET.get("genre", "").strip()
    selected_artist = request.GET.get("artist", "").strip()
    selected_album = request.GET.get("album", "").strip()

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

    if selected_artist:
        artists_qs = artists_qs.filter(pk=selected_artist)
        albums_qs = albums_qs.filter(artist_id=selected_artist)
        songs_qs = songs_qs.filter(artist_id=selected_artist)

    if selected_album:
        albums_qs = albums_qs.filter(pk=selected_album)
        songs_qs = songs_qs.filter(album_id=selected_album)

    if selected_genre:
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

    context = {
        "query": query,
        "result_type": result_type,
        "selected_genre": selected_genre,
        "selected_artist": selected_artist,
        "selected_album": selected_album,
        "artists": artists_qs,
        "albums": albums_qs,
        "songs": songs_qs,
        "favorite_song_ids": _favorite_song_ids(request),
        "artist_count": artists_qs.count(),
        "album_count": albums_qs.count(),
        "song_count": songs_qs.count(),
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
    ).order_by("title")[:6]:
        results.append(
            {
                "type": "Song",
                "label": f"{song.title} - {song.artist.name}",
                "url": reverse("song-detail", args=[song.pk]),
            }
        )

    return JsonResponse({"results": results[:10]})


def artist_detail(request, pk):
    artist = get_object_or_404(Artist, pk=pk)
    albums_qs = Album.objects.filter(artist=artist).order_by("-release_date", "title")
    songs_qs = Song.objects.filter(artist=artist).select_related("album").order_by("title")

    context = {
        "artist": artist,
        "albums": albums_qs,
        "songs": songs_qs,
        "favorite_song_ids": _favorite_song_ids(request),
        **_common_context(),
    }
    return render(request, "music/artist_detail.html", context)


def album_detail(request, pk):
    album = get_object_or_404(Album.objects.select_related("artist"), pk=pk)
    songs_qs = Song.objects.filter(album=album).select_related("artist").order_by("title")

    context = {
        "album": album,
        "songs": songs_qs,
        "favorite_song_ids": _favorite_song_ids(request),
        **_common_context(),
    }
    return render(request, "music/album_detail.html", context)


def song_detail(request, pk):
    song = get_object_or_404(Song.objects.select_related("artist", "album"), pk=pk)
    related_songs = (
        Song.objects.select_related("artist", "album")
        .filter(artist=song.artist)
        .exclude(pk=song.pk)
        .order_by("title")[:6]
    )

    context = {
        "song": song,
        "related_songs": related_songs,
        "default_platform_links": _song_platform_links(song),
        "is_favorite": song.id in _favorite_song_ids(request),
        "favorite_song_ids": _favorite_song_ids(request),
        **_common_context(),
    }
    return render(request, "music/song_detail.html", context)


def listen_links(request):
    songs_with_links = Song.objects.select_related("artist", "album").exclude(youtube_link="").order_by("title")
    context = {
        "songs": songs_with_links,
        "favorite_song_ids": _favorite_song_ids(request),
        **_common_context(),
    }
    return render(request, "music/listen_links.html", context)


def song_platform_options(request, pk):
    song = get_object_or_404(Song.objects.select_related("artist"), pk=pk)
    country = request.GET.get("country", "")
    links = _song_platform_links(song, country_code=country)
    return JsonResponse({"country": country.upper(), "links": links})


@require_POST
def toggle_favorite_song(request, pk):
    song = get_object_or_404(Song, pk=pk)
    session_key = _ensure_session_key(request)
    favorite, created = FavoriteSong.objects.get_or_create(session_key=session_key, song=song)

    if created:
        return JsonResponse({"ok": True, "is_favorite": True})

    favorite.delete()
    return JsonResponse({"ok": True, "is_favorite": False})


def favorite_songs(request):
    session_key = _ensure_session_key(request)
    songs_qs = (
        Song.objects.select_related("artist", "album")
        .filter(favorites__session_key=session_key)
        .order_by("title")
        .distinct()
    )

    context = {
        "songs": songs_qs,
        "favorite_song_ids": _favorite_song_ids(request),
        **_common_context(),
    }
    return render(request, "music/favorites.html", context)


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


def delete_artist(request, pk):
    artist = get_object_or_404(Artist, pk=pk)

    if request.method == "POST":
        artist.delete()
        return redirect("artists")

    return render(request, "music/delete_artist.html", {"artist": artist, "cancel_url": "artists"})


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


def delete_album(request, pk):
    album = get_object_or_404(Album, pk=pk)

    if request.method == "POST":
        album.delete()
        return redirect("albums")

    return render(request, "music/delete_album.html", {"album": album, "cancel_url": "albums"})


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


def delete_song(request, pk):
    song = get_object_or_404(Song, pk=pk)

    if request.method == "POST":
        song.delete()
        return redirect("songs")

    return render(request, "music/delete_song.html", {"song": song, "cancel_url": "songs"})
