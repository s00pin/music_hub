from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("music", "0002_alter_album_cover_alter_artist_image_favoritesong"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_song_title ON music_song(title);
                CREATE INDEX IF NOT EXISTS idx_song_genre ON music_song(genre);
                CREATE INDEX IF NOT EXISTS idx_artist_name ON music_artist(name);
                CREATE INDEX IF NOT EXISTS idx_album_title ON music_album(title);
                CREATE INDEX IF NOT EXISTS idx_song_artist_id ON music_song(artist_id);
                CREATE INDEX IF NOT EXISTS idx_song_album_id ON music_song(album_id);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS idx_song_title;
                DROP INDEX IF EXISTS idx_song_genre;
                DROP INDEX IF EXISTS idx_artist_name;
                DROP INDEX IF EXISTS idx_album_title;
                DROP INDEX IF EXISTS idx_song_artist_id;
                DROP INDEX IF EXISTS idx_song_album_id;
            """,
        )
    ]
