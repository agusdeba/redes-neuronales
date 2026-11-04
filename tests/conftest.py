"""Aisla data/, logs/ y reports/ en un directorio temporal antes de importar el pipeline."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="rn_test_")
os.environ["RN_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["RN_LOGS_DIR"] = str(Path(_TMP) / "logs")
os.environ["RN_REPORTS_DIR"] = str(Path(_TMP) / "reports")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"
