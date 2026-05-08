"""
現在価格・変化率・売買シグナルをテキストで出力する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reports.daily_report import generate

if __name__ == "__main__":
    print(generate())
