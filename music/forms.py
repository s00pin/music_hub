from django import forms

from .models import Album, Artist, MetadataReport, Song


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
        fields = ["name", "image", "image_url"]


class AlbumForm(StyledModelForm):
    class Meta:
        model = Album
        fields = ["title", "artist", "cover", "cover_url", "release_date"]
        widgets = {
            "release_date": forms.DateInput(attrs={"type": "date"}),
        }


class MetadataReportForm(StyledModelForm):
    target_kind = forms.ChoiceField(
        choices=MetadataReport.TARGET_KIND_CHOICES,
        widget=forms.HiddenInput(),
    )
    target_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput())

    class Meta:
        model = MetadataReport
        fields = ["issue_type", "details"]
        widgets = {
            "details": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 1000,
                    "placeholder": "Tell us what is missing or incorrect.",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        target_kind = cleaned_data.get("target_kind")
        target_id = cleaned_data.get("target_id")

        model_map = {
            MetadataReport.TARGET_SONG: Song,
            MetadataReport.TARGET_ALBUM: Album,
            MetadataReport.TARGET_ARTIST: Artist,
        }

        model_class = model_map.get(target_kind)
        if not model_class:
            self.add_error("target_kind", "Invalid report target.")
            return cleaned_data

        try:
            target = model_class.objects.get(pk=target_id)
        except model_class.DoesNotExist:
            self.add_error("target_id", "Selected item was not found.")
            return cleaned_data

        cleaned_data["target"] = target
        self.instance.song = target if target_kind == MetadataReport.TARGET_SONG else None
        self.instance.album = target if target_kind == MetadataReport.TARGET_ALBUM else None
        self.instance.artist = target if target_kind == MetadataReport.TARGET_ARTIST else None
        return cleaned_data

    def save_for_user(self, user):
        if not self.is_valid():
            raise ValueError("Cannot save invalid MetadataReportForm.")

        report = MetadataReport(
            user=user,
            issue_type=self.cleaned_data["issue_type"],
            details=self.cleaned_data.get("details", "").strip(),
        )

        target_kind = self.cleaned_data["target_kind"]
        target = self.cleaned_data["target"]

        if target_kind == MetadataReport.TARGET_SONG:
            report.song = target
        elif target_kind == MetadataReport.TARGET_ALBUM:
            report.album = target
        elif target_kind == MetadataReport.TARGET_ARTIST:
            report.artist = target

        report.full_clean()
        report.save()
        return report
