from django import forms

from .models import Album, Artist, Song


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            css_class = "form-control"

            if isinstance(widget, forms.Select):
                css_class = "form-select"

            existing = widget.attrs.get("class", "").strip()
            widget.attrs["class"] = f"{existing} {css_class}".strip()


class SongForm(StyledModelForm):
    class Meta:
        model = Song
        fields = ["title", "artist", "album", "genre", "youtube_link", "release_date"]
        widgets = {
            "release_date": forms.DateInput(attrs={"type": "date"}),
        }


class ArtistForm(StyledModelForm):
    class Meta:
        model = Artist
        fields = ["name", "image"]


class AlbumForm(StyledModelForm):
    class Meta:
        model = Album
        fields = ["title", "artist", "cover", "release_date"]
        widgets = {
            "release_date": forms.DateInput(attrs={"type": "date"}),
        }
