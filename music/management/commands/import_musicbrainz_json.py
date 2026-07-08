import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from music.services import import_musicbrainz_release_payloads


class Command(BaseCommand):
    help = "Import MusicBrainz release JSON payloads into local Artist/Album/Song tables."

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=str, help="Path to a MusicBrainz JSON file")
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional maximum number of release objects to import",
        )

    def handle(self, *args, **options):
        json_file = Path(options["json_file"]).expanduser()
        if not json_file.exists():
            raise CommandError(f"File not found: {json_file}")

        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc

        if isinstance(payload, dict) and isinstance(payload.get("releases"), list):
            releases = payload["releases"]
        elif isinstance(payload, list):
            releases = payload
        elif isinstance(payload, dict):
            releases = [payload]
        else:
            raise CommandError("Unsupported JSON shape. Expected release dict/list or {'releases': [...]} payload.")

        limit = max(int(options["limit"] or 0), 0)
        if limit:
            releases = releases[:limit]

        summary = import_musicbrainz_release_payloads(releases)
        self.stdout.write(self.style.SUCCESS("Import complete."))
        self.stdout.write(f"Artists created: {summary['artists_created']}")
        self.stdout.write(f"Albums created: {summary['albums_created']}")
        self.stdout.write(f"Songs created: {summary['songs_created']}")
        if summary["errors"]:
            self.stdout.write(self.style.WARNING(f"Errors: {len(summary['errors'])}"))
