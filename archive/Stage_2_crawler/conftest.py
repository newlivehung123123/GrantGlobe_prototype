"""
Root-level pytest conftest.
Ensures the project root is on sys.path so that ``import grantglobe_crawler``
works from any test file without requiring an editable install.
"""
import sys
from pathlib import Path

# Insert project root (the directory containing this file) at the front of
# sys.path so that ``grantglobe_crawler`` is importable during test collection.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
