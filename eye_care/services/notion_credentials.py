"""Windows-user-bound encrypted storage. No plaintext fallback."""
from pathlib import Path

from .notion_client import NotionError


class NotionCredentials:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "notion_credentials.dat"

    def exists(self):
        return self.path.is_file()

    def save(self, token: str):
        try:
            import win32crypt
            encrypted = win32crypt.CryptProtectData(token.encode("utf-8"), "EyE Care Notion", None, None, None, 0)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_bytes(encrypted)
            temporary.replace(self.path)
        except Exception:
            raise NotionError("无法安全保存密钥，设置未保存。请在 Windows 当前用户下重试。") from None

    def load(self):
        if not self.exists():
            raise NotionError("请先在同步设置中填写并保存 Notion API 密钥。")
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(self.path.read_bytes(), None, None, None, 0)[1].decode("utf-8")
        except Exception:
            raise NotionError("无法解密密钥；换电脑或 Windows 用户后，需要重新填写密钥。") from None

    def clear(self):
        self.path.unlink(missing_ok=True)
