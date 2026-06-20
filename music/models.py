from django.db import models

# Create your models here.
class Song(models.Model):
    title = models.CharField(max_length=200)
    artist = models.CharField(max_length=200)
    genre = models.CharField(max_length=100)
    released_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title