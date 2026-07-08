from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


METADATA_REPORT_ONE_TARGET_CONDITION = (
    Q(song__isnull=False, album__isnull=True, artist__isnull=True)
    | Q(song__isnull=True, album__isnull=False, artist__isnull=True)
    | Q(song__isnull=True, album__isnull=True, artist__isnull=False)
)


    
#artist model
class Artist(models.Model):
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to='artists/', blank=True, null=True)
    image_url = models.URLField(blank=True)
    mbid = models.UUIDField(null=True, blank=True, unique=True, db_index=True)

    def __str__(self):
        return self.name

    @property
    def image_src(self):
        if self.image:
            try:
                return self.image.url
            except Exception:
                pass
        if self.image_url:
            return self.image_url
        return ""

#album model
class Album(models.Model):
    title = models.CharField(max_length=200)
    mbid = models.UUIDField(null=True, blank=True, unique=True, db_index=True)
    artist = models.ForeignKey(
        Artist,
        on_delete=models.CASCADE
    )

    cover = models.ImageField(
        upload_to='albums/',
        blank=True,
        null=True
    )
    cover_url = models.URLField(blank=True)

    release_date = models.DateField(
        null=True,
        blank=True
    )

    def __str__(self):
        return self.title

    @property
    def cover_src(self):
        if self.cover:
            try:
                return self.cover.url
            except Exception:
                pass
        if self.cover_url:
            return self.cover_url
        return ""

#Song model
class Song(models.Model):
    title = models.CharField(max_length=200)
    mbid = models.UUIDField(null=True, blank=True, unique=True, db_index=True)

    artist = models.ForeignKey(
        Artist,
        on_delete=models.CASCADE
    )

    album = models.ForeignKey(
        Album,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    genre = models.CharField(max_length=100)

    youtube_link = models.URLField(
        blank=True
    )

    release_date = models.DateField(
        null=True,
        blank=True
    )

    def __str__(self):
        return self.title

class FavoriteSong(models.Model):
    session_key = models.CharField(max_length=40, db_index=True, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_songs",
        null=True,
        blank=True,
    )
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session_key", "song"],
                condition=Q(session_key__isnull=False),
                name="unique_session_song_favorite",
            ),
            models.UniqueConstraint(
                fields=["user", "song"],
                condition=Q(user__isnull=False),
                name="unique_user_song_favorite",
            ),
        ]

    def __str__(self):
        return f"{self.session_key} -> {self.song.title}"


class LikeSong(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liked_songs",
    )
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "song"],
                name="unique_user_song_like",
            ),
        ]

    def __str__(self):
        return f"{self.user} likes {self.song.title}"


class MetadataReport(models.Model):
    TARGET_SONG = "song"
    TARGET_ALBUM = "album"
    TARGET_ARTIST = "artist"
    TARGET_KIND_CHOICES = [
        (TARGET_SONG, "Song"),
        (TARGET_ALBUM, "Album"),
        (TARGET_ARTIST, "Artist"),
    ]

    ISSUE_INCOMPLETE = "incomplete"
    ISSUE_FALSE_INFO = "false_info"
    ISSUE_CHOICES = [
        (ISSUE_INCOMPLETE, "Incomplete info"),
        (ISSUE_FALSE_INFO, "False info"),
    ]

    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="metadata_reports",
    )
    issue_type = models.CharField(max_length=20, choices=ISSUE_CHOICES)
    details = models.TextField(blank=True)
    song = models.ForeignKey(Song, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    album = models.ForeignKey(Album, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=METADATA_REPORT_ONE_TARGET_CONDITION,
                name="metadata_report_exactly_one_target",
            )
        ]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["issue_type", "created_at"]),
        ]

    def __str__(self):
        target = self.song or self.album or self.artist
        return f"{self.user} reported {target} ({self.issue_type})"

    def clean(self):
        super().clean()
        targets = [self.song_id, self.album_id, self.artist_id]
        if sum(1 for target_id in targets if target_id is not None) != 1:
            raise ValidationError("A report must target exactly one entity.")

    @property
    def target(self):
        return self.song or self.album or self.artist

    @property
    def target_kind(self):
        if self.song_id:
            return self.TARGET_SONG
        if self.album_id:
            return self.TARGET_ALBUM
        if self.artist_id:
            return self.TARGET_ARTIST
        return ""
