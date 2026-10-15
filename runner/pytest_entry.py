"""Bootstrap pytest with explicit application paths, also for isolated Windows Python."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "runner"), str(ROOT)]

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main(sys.argv[1:]))
