import json
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.apps import apps
from django.core.management import BaseCommand, CommandError, call_command
from django.utils import timezone


class Command(BaseCommand):
    help = 'Create a timestamped backup of application data. Writes a JSON export and, for SQLite, also copies the database file.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=str(settings.BASE_DIR / 'backups'),
            help='Directory where backup files will be written.',
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir']).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        json_backup = output_dir / f'backup-{timestamp}.json'
        manifest_backup = output_dir / f'backup-{timestamp}.manifest.json'

        self.stdout.write(f'Writing JSON backup to {json_backup}')
        with json_backup.open('w', encoding='utf-8') as backup_file:
            call_command(
                'dumpdata',
                '--natural-foreign',
                '--natural-primary',
                '--indent',
                '2',
                stdout=backup_file,
            )

        engine = settings.DATABASES['default']['ENGINE']
        sqlite_copy = None
        if engine == 'django.db.backends.sqlite3':
            db_path = Path(settings.DATABASES['default']['NAME'])
            if db_path.exists():
                sqlite_copy = output_dir / f'{db_path.stem}-{timestamp}{db_path.suffix}'
                shutil.copy2(db_path, sqlite_copy)
                self.stdout.write(f'Copied SQLite database to {sqlite_copy}')
            else:
                self.stdout.write('SQLite database file is not a regular on-disk file. Skipping raw database copy and keeping the JSON export only.')

        manifest = self.build_manifest(json_backup, sqlite_copy, engine)
        with manifest_backup.open('w', encoding='utf-8') as manifest_file:
            json.dump(manifest, manifest_file, indent=2)
            manifest_file.write('\n')

        self.stdout.write(self.style.SUCCESS('Backup completed successfully.'))
        self.stdout.write(f'JSON export: {json_backup}')
        self.stdout.write(f'Manifest: {manifest_backup}')
        if sqlite_copy:
            self.stdout.write(f'SQLite copy: {sqlite_copy}')

    def build_manifest(self, json_backup, sqlite_copy, engine):
        database_config = settings.DATABASES['default']
        database_name = database_config.get('NAME', '')
        if engine == 'django.db.backends.sqlite3':
            database_name = Path(database_name).name

        return {
            'created_at': timezone.now().isoformat(),
            'format': 'django-dumpdata-json',
            'database': {
                'provider': 'Supabase' if getattr(settings, 'SUPABASE_DATABASE_URL', '') else 'SQLite',
                'engine': engine,
                'name': str(database_name),
                'host': database_config.get('HOST') or 'local',
                'sslmode': database_config.get('OPTIONS', {}).get('sslmode', ''),
            },
            'files': {
                'json_export': json_backup.name,
                'sqlite_copy': sqlite_copy.name if sqlite_copy else '',
            },
            'record_counts': {
                model._meta.label: model.objects.count()
                for model in apps.get_models()
            },
        }
