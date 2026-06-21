from django.db import models


    
#artist model
class Artist(models.Model):
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to='artists/', blank=True, null=True)

    def __str__(self):
        return self.name

#album model
class Album(models.Model):
    title = models.CharField(max_length=200)
    artist = models.ForeignKey(
        Artist,
        on_delete=models.CASCADE
    )

    cover = models.ImageField(
        upload_to='albums/',
        blank=True,
        null=True
    )

    release_date = models.DateField(
        null=True,
        blank=True
    )

    def __str__(self):
        return self.title

#Song model
class Song(models.Model):
    title = models.CharField(max_length=200)

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