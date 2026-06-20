from django.http import HttpResponse
from django.shortcuts import render
from .models import Song

def home(request):
    return HttpResponse("Hello World")

def song_list(request):
    songs = Song.objects.all()
    return render(request, 'music/song_list.html', {'songs': songs})