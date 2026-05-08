from pathlib import Path
from src.utils.logger import get_logger

log = get_logger(__name__)


class KillSwitch:
    """STOP_TRADING ファイルが存在したら全取引を停止する。"""

    def __init__(self, stop_file: Path):
        self.stop_file = stop_file

    def is_active(self) -> bool:
        active = self.stop_file.exists()
        if active:
            log.warning(f"KILL SWITCH ON: {self.stop_file} が存在します。全取引停止中。")
        return active

    def activate(self, reason: str = "手動停止"):
        self.stop_file.write_text(reason, encoding="utf-8")
        log.warning(f"KILL SWITCH 有効化: {reason}")

    def deactivate(self):
        if self.stop_file.exists():
            self.stop_file.unlink()
            log.info("KILL SWITCH 解除済み")
