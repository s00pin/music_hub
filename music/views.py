from django.http import HttpResponse
from django.shortcuts import render
from .models import Song, Artist, Album

def home(request):
    return render(request, 'music/home.html')

def songs(request):
    songs = Song.objects.all()
    return render(request, 'music/songs.html', {'songs': songs})

def artists(request):
    artists = Artist.objects.all()
    return render(request, 'music/artists.html', {'artists': artists})

def albums(request):
    albums = Album.objects.all()
    return render(request, 'music/albums.html', {'albums': albums})