"""Visible Zhuque website adapter; never silently substitutes a local score."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


WEB_URL = "https://matrix.tencent.com/ai-detect/"
MIN_WEB_CHARS = 351  # Observed website validation: 检测文本长度需大于350字.


class BrowserDetectionError(RuntimeError):
    def __init__(self, reason, message, evidence=None):
        super().__init__(message)
        self.reason = reason
        self.evidence = evidence or {}


def default_profile_dir():
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    return base / "ruanzhu-kit" / "zhusque-browser"


class BrowserDetector:
    """Use a persistent, visible Chrome profile, separate from personal Chrome.

    Each request starts a bounded driver subprocess. Chrome remains open so the
    user can complete a CAPTCHA/login and retry the same text without losing it.
    The same profile is reused across documents; no quota-reset/incognito loop.
    """

    def __init__(self, material_dir, timeout=120, profile_dir=None, node=None):
        self.material_dir = Path(material_dir).resolve()
        self.timeout = max(10, min(float(timeout), 600))
        self.profile_dir = Path(profile_dir or default_profile_dir()).resolve()
        self.node = (node or os.environ.get("RUANZHU_NODE_EXECUTABLE")
                     or os.environ.get("RUANZHU_NODE") or shutil.which("node"))
        self._process = None

    def detect(self, text, request_id, force=False):
        if not isinstance(text, str) or len(text.strip()) < MIN_WEB_CHARS:
            raise BrowserDetectionError("unsupported", "朱雀网页要求超过350字；请合并相邻原文后复核，不能补写无关内容凑字数。")
        if not self.node:
            raise BrowserDetectionError("unavailable", "网页检测需要 Node.js 和 Playwright，请安装桌面应用依赖后重试。")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(request_id))[:80].strip(".") or "request"
        payload = {
            "text": text,
            "request_id": safe_id,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "material_dir": str(self.material_dir),
            "profile_dir": str(self.profile_dir),
            "timeout_ms": int(self.timeout * 1000),
            "force": bool(force),
        }
        command = [str(self.node), str(Path(__file__).with_name("zhusque-browser.js"))]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, text=True, encoding="utf-8")
            stdout, _stderr = self._process.communicate(json.dumps(payload, ensure_ascii=False),
                                                        timeout=self.timeout + 15)
            try:
                result = json.loads(stdout)
            except (ValueError, TypeError) as exc:
                raise BrowserDetectionError("unavailable", "网页驱动没有返回有效结果；未将本次检测记为通过。") from exc
            if not isinstance(result, dict):
                raise BrowserDetectionError("unsupported", "网页驱动结果格式无效。")
            if self._process.returncode or result.get("status") != "success":
                reason = result.get("reason", "unavailable")
                if reason not in {"quota", "captcha", "login", "unavailable", "unsupported"}:
                    reason = "unavailable"
                raise BrowserDetectionError(reason, result.get("message", "网页检测未完成。"), result.get("evidence"))
            # Preserve provenance after the common parser's strict numeric check.
            from zhusque_check import parse_result
            try:
                parse_result(result)
            except (ValueError, TypeError) as exc:
                raise BrowserDetectionError("unsupported", "网页结果缺少有效分类占比；未将本次检测记为通过。", result.get("evidence")) from exc
            return result
        except subprocess.TimeoutExpired as exc:
            self.close()
            raise BrowserDetectionError("unavailable", "网页检测超时；已保留浏览器窗口与待检测内容。") from exc
        except OSError as exc:
            raise BrowserDetectionError("unavailable", "无法启动网页检测驱动，请检查 Node.js 路径。") from exc
        finally:
            self._process = None

    def close(self):
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            self._process.communicate()
