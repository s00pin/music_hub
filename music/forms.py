from django import forms
from .models import Song

class SongForm(forms.ModelForm):

    class Meta:
        model = Song
        fields = [
            'title',
            'artist',
            'album',
            'genre',
            'youtube_link',
            'release_date'
        ]

        widgets = {
            'release_date': forms.DateInput(attrs={'type': 'date'}),
        }