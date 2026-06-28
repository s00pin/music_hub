from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from .models import Song, Artist, Album
from .forms import SongForm


def home(request):
    return render(request, "music/home.html")


def songs(request):
    songs = Song.objects.all()
    return render(request, "music/songs.html", {"songs": songs})


def artists(request):
    artists = Artist.objects.all()
    return render(request, "music/artists.html", {"artists": artists})

def albums(request):
    albums = Album.objects.all()
    return render(request, "music/albums.html", {"albums": albums})

def add_song(request):

    if request.method == "POST":
        form = SongForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("songs")

    else:
        form = SongForm()

    return render(request, "music/song_form.html", {
        "form": form,
        "title": "Add Song"
    })


def edit_song(request, pk):

    song = get_object_or_404(Song, pk=pk)

    if request.method == "POST":

        form = SongForm(request.POST, instance=song)

        if form.is_valid():
            form.save()
            return redirect("songs")

    else:
        form = SongForm(instance=song)

    return render(request, "music/song_form.html", {
        "form": form,
        "title": "Edit Song"
    })


def delete_song(request, pk):

    song = get_object_or_404(Song, pk=pk)

    if request.method == "POST":
        song.delete()
        return redirect("songs")

    return render(request, "music/delete_song.html", {
        "song": song
    })