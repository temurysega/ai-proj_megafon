"""Обёртка запуска хуков из любой рабочей папки: python scripts/hook.py <событие>."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from strategist.hooks import main  # noqa: E402

main()
