import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Timer
from urllib.parse import urlsplit

import httpx

from app.arxiv import (
    API_URL, ERROR_PHASES, MAX_METADATA_BYTES, MAX_PDF_BYTES, ArxivError, DownloadReceipt,
    ProviderReply, invalid_response, normalize_arxiv_id, validate_pdf_url,
)


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> int:
    try:
        if value is None or len(value) > 2048:
            return 60
        value = value.strip()
        if re.fullmatch(r"[0-9]+", value):
            seconds = int(value) if len(value) < 9 else 86400
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return 60
            seconds = math.ceil((target - (now or datetime.now(timezone.utc))).total_seconds())
        return max(3, min(86400, seconds))
    except (ValueError, TypeError, OverflowError):
        return 60


def validate_request(url: str, params: dict | None, destination: Path | None) -> None:
    if url == API_URL and destination is None:
        if not isinstance(params, dict) or not 1 <= len(params) <= 5:
            raise invalid_response()
        if set(params) == {"id_list", "max_results"} and type(params["max_results"]) is int and params["max_results"] == 1:
            try:
                normalize_arxiv_id(params["id_list"])
                return
            except ValueError:
                raise invalid_response() from None
        if (
            set(params) == {"search_query", "start", "max_results", "sortBy", "sortOrder"}
            and isinstance(params["search_query"], str) and 1 <= len(params["search_query"]) <= 1000
            and type(params["start"]) is int and 0 <= params["start"] <= 1000
            and type(params["max_results"]) is int and 1 <= params["max_results"] <= 20
            and params["sortBy"] == "relevance" and params["sortOrder"] == "descending"
        ):
            return
        raise invalid_response()
    try:
        path = urlsplit(url).path
        if destination is None or params is not None or not path.startswith("/pdf/"):
            raise ValueError
        identifier = path[len("/pdf/"):]
        if identifier.endswith(".pdf"):
            identifier = identifier[:-4]
        validate_pdf_url(url, normalize_arxiv_id(identifier))
    except (ValueError, TypeError, AttributeError):
        raise ArxivError("UNSAFE_SOURCE_URL", "请求地址不符合允许的论文来源") from None


def perform_request(
    url: str, *, params: dict | None, destination: Path | None,
    user_agent: str, timeout_seconds: float,
) -> ProviderReply:
    validate_request(url, params, destination)
    maximum = MAX_PDF_BYTES if destination is not None else MAX_METADATA_BYTES
    timeout = httpx.Timeout(
        min(5.0, timeout_seconds),
        read=min(15.0 if destination is None else 5.0, timeout_seconds),
    )
    phase = "response_headers"
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            with client.stream("GET", url, params=params, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"}) as response:
                if any(len(response.headers[name]) > 2048 for name in ["location", "retry-after"] if name in response.headers):
                    raise invalid_response()
                if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                    raise invalid_response()
                headers = {name: response.headers[name] for name in ["location", "retry-after"] if name in response.headers}
                if response.status_code != 200:
                    return ProviderReply(response.status_code, headers, b"")
                declared = response.headers.get("content-length")
                if declared is not None:
                    if re.fullmatch(r"[0-9]{1,20}", declared) is None:
                        raise invalid_response()
                    if int(declared) > maximum:
                        raise ArxivError("FILE_TOO_LARGE", "论文文件最大为 20 MiB") if destination else invalid_response()
                size = 0
                body = bytearray()
                header = b""
                digest = hashlib.sha256()
                output = destination.open("wb") if destination is not None else None
                phase = "response_body"
                try:
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > maximum:
                            raise ArxivError("FILE_TOO_LARGE", "论文文件最大为 20 MiB") if destination else invalid_response()
                        if output is not None:
                            header = (header + chunk)[:5]
                            digest.update(chunk)
                            output.write(chunk)
                        else:
                            body.extend(chunk)
                    if output is not None:
                        if header != b"%PDF-":
                            raise ArxivError("INVALID_PDF", "下载文件缺少 PDF 文件头")
                        output.flush()
                        os.fsync(output.fileno())
                finally:
                    if output is not None:
                        output.close()
                receipt = DownloadReceipt(size, digest.hexdigest()) if destination is not None else None
                return ProviderReply(response.status_code, headers, bytes(body), receipt)
    except httpx.HTTPError as error:
        if isinstance(error, (httpx.ConnectTimeout, httpx.ConnectError)):
            phase = "connect"
        elif isinstance(error, (httpx.WriteTimeout, httpx.WriteError)):
            phase = "write"
        elif isinstance(error, httpx.PoolTimeout):
            phase = "pool"
        elif not isinstance(error, (httpx.ReadTimeout, httpx.ReadError)):
            phase = "unknown"
        if isinstance(error, httpx.TimeoutException):
            raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True, phase=phase) from None
        raise ArxivError("ARXIV_UNAVAILABLE", "arXiv 网络服务暂不可用", retryable=True, phase=phase) from None
    except OSError:
        raise ArxivError("STORAGE_WRITE_FAILED", "导入临时文件写入失败", retryable=True) from None


def launch_fetch_process() -> subprocess.Popen:
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    return subprocess.Popen(
        [sys.executable, "-B", "-m", "app.arxiv_transport", "--fetch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    if process.stdin is not None:
        process.stdin.close()
    if process.stdout is not None:
        process.stdout.close()


class SupervisedArxivTransport:
    def __init__(
        self, contact_email: str,
        permits: Callable[[], AbstractContextManager[Callable[[int], None]]],
        *, cancelled: Callable[[], bool] | None = None,
    ):
        if (
            not isinstance(contact_email, str) or len(contact_email) > 254
            or re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", contact_email) is None
        ):
            raise ValueError("A contact email is required")
        self.user_agent = f"LiteratureResearchAssistant/0.1 (contact: {contact_email})"
        self.permits = permits
        self.cancelled = cancelled or (lambda: False)

    def check_active(self, deadline: float) -> None:
        if self.cancelled():
            raise ArxivError("REQUEST_CANCELLED", "论文来源请求已中止", retryable=True)
        if not math.isfinite(deadline) or time.monotonic() >= deadline:
            raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True, phase="deadline")

    def request(
        self, url: str, *, params: dict | None = None,
        destination: Path | None = None, deadline: float,
    ) -> ProviderReply:
        validate_request(url, params, destination)
        deadline = min(deadline, time.monotonic() + (90 if destination is not None else 20))
        self.check_active(deadline)
        created = False
        try:
            with self.permits() as cooldown:
                self.check_active(deadline)
                if destination is not None:
                    destination = Path(destination)
                    with destination.open("xb"):
                        pass
                    created = True
                reply = self._execute(url, params=params, destination=destination, deadline=deadline)
                self.check_active(deadline)
                if reply.status_code in {429, 503}:
                    cooldown(retry_after_seconds(reply.headers.get("retry-after")))
                if created and reply.status_code != 200:
                    destination.unlink(missing_ok=True)
                    created = False
                return reply
        except BaseException as error:
            if created:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
            if isinstance(error, OSError):
                raise ArxivError("STORAGE_WRITE_FAILED", "导入临时文件不可写", retryable=True) from None
            raise

    def _execute(self, url: str, *, params: dict | None, destination: Path | None, deadline: float) -> ProviderReply:
        process = launch_fetch_process()
        command = json.dumps({
            "url": url, "params": params, "destination": str(destination.resolve()) if destination is not None else None,
            "user_agent": self.user_agent, "timeout_seconds": max(.01, deadline - time.monotonic()),
        }).encode("utf-8")
        try:
            first = True
            while True:
                self.check_active(deadline)
                try:
                    output, _ = process.communicate(input=command if first else None, timeout=min(.1, max(.001, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    first = False
            self.check_active(deadline)
            if process.returncode == 124:
                raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True, phase="deadline")
            if process.returncode != 0 or len(output) > 3 * MAX_METADATA_BYTES:
                raise invalid_response()
            try:
                result = json.loads(output)
                if "error" in result:
                    code = result["error"]
                    messages = {
                        "ARXIV_TIMEOUT": "arXiv 请求超时", "ARXIV_UNAVAILABLE": "arXiv 网络服务暂不可用",
                        "ARXIV_INVALID_RESPONSE": "arXiv 返回了不合法的响应", "UNSAFE_SOURCE_URL": "请求地址不符合允许的论文来源",
                        "FILE_TOO_LARGE": "论文文件最大为 20 MiB", "INVALID_PDF": "下载文件缺少 PDF 文件头",
                        "STORAGE_WRITE_FAILED": "导入临时文件写入失败",
                    }
                    if code not in messages:
                        raise ValueError
                    phase = result.get("phase", "unknown")
                    if not isinstance(phase, str) or phase not in ERROR_PHASES:
                        raise ValueError
                    raise ArxivError(code, messages[code], retryable=code in {"ARXIV_TIMEOUT", "ARXIV_UNAVAILABLE", "STORAGE_WRITE_FAILED"}, phase=phase)
                status = result["status_code"]
                headers = result["headers"]
                if type(status) is not int or not 100 <= status <= 599 or not isinstance(headers, dict):
                    raise ValueError
                if any(key not in {"location", "retry-after"} or not isinstance(value, str) or len(value) > 2048 for key, value in headers.items()):
                    raise ValueError
                body = base64.b64decode(result["body"], validate=True)
                if len(body) > MAX_METADATA_BYTES:
                    raise ValueError
                receipt = DownloadReceipt(**result["receipt"]) if result["receipt"] is not None else None
                if destination is not None and status == 200 and (receipt is None or destination.stat().st_size != receipt.size_bytes):
                    raise ValueError
                return ProviderReply(status, headers, body, receipt)
            except (ValueError, KeyError, TypeError):
                raise invalid_response() from None
        finally:
            stop_process(process)


def main() -> None:
    watchdog = None
    try:
        command = json.loads(sys.stdin.buffer.read(8193))
        seconds = command["timeout_seconds"]
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or not 0 < seconds <= 90:
            raise ValueError("Invalid deadline")
        watchdog = Timer(seconds, lambda: os._exit(124))
        watchdog.daemon = True
        watchdog.start()
        reply = perform_request(
            command["url"], params=command["params"], destination=Path(command["destination"]) if command["destination"] else None,
            user_agent=command["user_agent"], timeout_seconds=command["timeout_seconds"],
        )
        result = {
            "status_code": reply.status_code, "headers": reply.headers,
            "body": base64.b64encode(reply.body).decode("ascii"),
            "receipt": {"size_bytes": reply.receipt.size_bytes, "sha256": reply.receipt.sha256} if reply.receipt else None,
        }
    except ArxivError as error:
        result = {"error": error.code, "phase": error.phase}
    except Exception:
        result = {"error": "ARXIV_INVALID_RESPONSE", "phase": "response_validation"}
    finally:
        if watchdog is not None:
            watchdog.cancel()
    sys.stdout.buffer.write(json.dumps(result, separators=(",", ":")).encode("utf-8"))


if __name__ == "__main__" and sys.argv[1:] == ["--fetch"]:
    main()
