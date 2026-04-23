#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    # [檢查點] 確保這裡指向你的專案設定檔 'emotion_project.settings'
    # 這行代碼讓 manage.py 能讀取到我們在 settings.py 裡做的所有修改 (時區、資料庫、App)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotion_project.settings')
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