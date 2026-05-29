#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


def relaunch_inside_project_venv():
    """Use the project virtual environment when manage.py is run with global Python."""
    if os.environ.get('SKIP_PROJECT_VENV_RELAUNCH'):
        return

    project_root = Path(__file__).resolve().parent
    venv_python = (project_root / '..' / '..' / 'venv' / 'Scripts' / 'python.exe').resolve()

    if not venv_python.exists():
        return

    current_python = Path(sys.executable).resolve()
    if current_python == venv_python:
        return

    os.environ['PROJECT_VENV_RELAUNCHED'] = '1'
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


def main():
    """Run administrative tasks."""
    relaunch_inside_project_venv()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
