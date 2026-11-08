"""Baidu Netdisk (xpan) helpers for longmemory daily backup.

Auth: device-code OAuth. Upload: precreate -> superfile2 -> create.
Tokens must be stored by the caller (single-use refresh_token).
"""
from __future__ import annotations

import hashlib
import json
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Optional

SLICE = 4 * 1024 * 1024  # non-VIP fixed slice size
UA = "pan.baidu.com"
OAUTH = "https://openapi.baidu.com/oauth/2.0"
XPAN = "https://pan.baidu.com/rest/2.0/xpan/file"
PCS_UPLOAD = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"


class BaiduError(RuntimeError):
    pass


def _req(
    url: str,
    *,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
    form: Optional[dict] = None,
    timeout: float = 60,
) -> dict | bytes:
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    body = data
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "json" in ctype or (raw[:1] in (b"{", b"[")):
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return raw
            return raw
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        try:
            j = json.loads(raw.decode("utf-8"))
        except Exception:
            raise BaiduError(f"HTTP {e.code}: {raw[:300]!r}") from e
        raise BaiduError(f"HTTP {e.code}: {j}") from e


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_file_slices(path: Path, slice_size: int = SLICE) -> tuple[list[str], int]:
    blocks: list[str] = []
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(slice_size)
            if not chunk:
                break
            blocks.append(md5_bytes(chunk))
            size += len(chunk)
    if not blocks:
        raise BaiduError("empty file cannot be uploaded")
    return blocks, size


def device_code(app_key: str) -> dict:
    q = urllib.parse.urlencode(
        {"response_type": "device_code", "client_id": app_key, "scope": "basic,netdisk"}
    )
    j = _req(f"{OAUTH}/device/code?{q}")
    if not isinstance(j, dict) or "device_code" not in j:
        raise BaiduError(f"device_code failed: {j}")
    return j


def poll_device_token(
    app_key: str,
    app_secret: str,
    device_code_val: str,
    *,
    interval: int = 5,
    expires_in: int = 300,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Optional[Callable[[], bool]] = None,
) -> dict:
    interval = max(5, int(interval or 5))
    deadline = time.time() + max(30, int(expires_in or 300))
    q_base = {
        "grant_type": "device_token",
        "code": device_code_val,
        "client_id": app_key,
        "client_secret": app_secret,
    }
    while time.time() < deadline:
        if should_stop and should_stop():
            raise BaiduError("bind cancelled")
        q = urllib.parse.urlencode(q_base)
        try:
            j = _req(f"{OAUTH}/token?{q}")
        except BaiduError as e:
            msg = str(e)
            if "authorization_pending" in msg or "slow_down" in msg:
                sleep_fn(interval + (3 if "slow_down" in msg else 0))
                continue
            if "expired_token" in msg or "device_code_expired" in msg:
                raise BaiduError("授权码已过期，请重新 /backup bind") from e
            if "access_denied" in msg:
                raise BaiduError("你拒绝了授权") from e
            raise
        if isinstance(j, dict) and j.get("access_token"):
            return j
        err = (j or {}).get("error") if isinstance(j, dict) else None
        if err in ("authorization_pending", "slow_down"):
            sleep_fn(interval + (3 if err == "slow_down" else 0))
            continue
        if err in ("expired_token", "device_code_expired"):
            raise BaiduError("授权码已过期，请重新 /backup bind")
        if err == "access_denied":
            raise BaiduError("你拒绝了授权")
        raise BaiduError(f"device_token unexpected: {j}")
    raise BaiduError("等待授权超时，请重新 /backup bind")


def refresh_token(app_key: str, app_secret: str, refresh: str) -> dict:
    q = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": app_key,
            "client_secret": app_secret,
        }
    )
    j = _req(f"{OAUTH}/token?{q}")
    if not isinstance(j, dict) or not j.get("access_token"):
        raise BaiduError(f"refresh failed: {j}")
    return j


def ensure_access(tokens: dict, app_key: str, app_secret: str, *, skew: int = 600) -> dict:
    """Return tokens dict, refreshing if access_token near expiry. Caller must save result."""
    exp = float(tokens.get("expires_at") or 0)
    if tokens.get("access_token") and time.time() < exp - skew:
        return tokens
    rt = tokens.get("refresh_token")
    if not rt:
        raise BaiduError("未绑定网盘，请先 /backup bind")
    j = refresh_token(app_key, app_secret, rt)
    out = dict(tokens)
    out["access_token"] = j["access_token"]
    out["refresh_token"] = j.get("refresh_token") or rt
    out["expires_in"] = int(j.get("expires_in") or 2592000)
    out["expires_at"] = time.time() + out["expires_in"]
    out["scope"] = j.get("scope") or out.get("scope") or ""
    return out


def pack_backup(
    data_root: Path,
    dest: Path,
    *,
    exclude_names: Iterable[str] = ("baidu_tokens.json",),
) -> Path:
    """Pack plugin data dir into tar.gz. Excludes token file and the dest archive itself."""
    data_root = Path(data_root)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    excl = set(exclude_names) | {dest.name}
    # also skip writing into itself if dest is under data_root
    dest_resolved = dest.resolve()

    def _ok(p: Path) -> bool:
        if p.name in excl:
            return False
        try:
            if p.resolve() == dest_resolved:
                return False
        except Exception:
            pass
        if p.name.startswith(".") and p.name not in (".imported",):
            # keep .imported marker but skip other dotfiles / __pycache__
            pass
        if p.name == "__pycache__":
            return False
        return True

    with tarfile.open(dest, "w:gz") as tar:
        if not data_root.exists():
            raise BaiduError(f"data root missing: {data_root}")
        for child in sorted(data_root.iterdir()):
            if not _ok(child):
                continue
            if child.is_dir():
                for f in sorted(child.rglob("*")):
                    if f.is_file() and _ok(f) and "__pycache__" not in f.parts:
                        tar.add(f, arcname=str(f.relative_to(data_root)))
            elif child.is_file():
                tar.add(child, arcname=child.name)
    if dest.stat().st_size == 0:
        raise BaiduError("archive is empty")
    return dest


def _remote_path(app_name: str, filename: str) -> str:
    name = (app_name or "AstrBot备份").strip().strip("/")
    return f"/apps/{name}/astrbot-backup/{filename}"


def upload_file(
    access_token: str,
    local_path: Path,
    *,
    app_name: str,
    remote_name: Optional[str] = None,
    slice_size: int = SLICE,
) -> dict:
    local_path = Path(local_path)
    remote_name = remote_name or local_path.name
    path = _remote_path(app_name, remote_name)
    blocks, size = md5_file_slices(local_path, slice_size)
    form = {
        "path": path,
        "size": str(size),
        "isdir": "0",
        "autoinit": "1",
        "rtype": "3",  # overwrite same name
        "block_list": json.dumps(blocks),
    }
    pre = _req(
        f"{XPAN}?method=precreate&access_token={urllib.parse.quote(access_token)}",
        method="POST",
        form=form,
        timeout=120,
    )
    if not isinstance(pre, dict):
        raise BaiduError(f"precreate bad response: {pre!r}")
    errno = pre.get("errno", 0)
    if errno not in (0, None):
        raise BaiduError(f"precreate errno={errno}: {pre}")
    # return_type 2 = rapid upload hit
    if pre.get("return_type") == 2:
        return {"ok": True, "rapid": True, "path": path, "precreate": pre}

    uploadid = pre.get("uploadid")
    if not uploadid:
        raise BaiduError(f"precreate missing uploadid: {pre}")
    need = pre.get("block_list")
    if need is None:
        need_idx = list(range(len(blocks)))
    else:
        need_idx = [int(x) for x in need]

    with local_path.open("rb") as f:
        for seq in need_idx:
            f.seek(seq * slice_size)
            chunk = f.read(slice_size)
            if not chunk:
                raise BaiduError(f"missing slice {seq}")
            q = urllib.parse.urlencode(
                {
                    "method": "upload",
                    "access_token": access_token,
                    "type": "tmpfile",
                    "path": path,
                    "uploadid": uploadid,
                    "partseq": str(seq),
                }
            )
            boundary = f"----longmemory{int(time.time())}{seq}"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="blob"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + chunk + f"\r\n--{boundary}--\r\n".encode("utf-8")
            up = _req(
                f"{PCS_UPLOAD}?{q}",
                method="POST",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                timeout=180,
            )
            if isinstance(up, dict) and up.get("error_code"):
                raise BaiduError(f"slice {seq} failed: {up}")

    create_form = {
        "path": path,
        "size": str(size),
        "isdir": "0",
        "rtype": "3",
        "uploadid": uploadid,
        "block_list": json.dumps(blocks),
    }
    created = _req(
        f"{XPAN}?method=create&access_token={urllib.parse.quote(access_token)}",
        method="POST",
        form=create_form,
        timeout=120,
    )
    if not isinstance(created, dict) or created.get("errno", 0) not in (0, None):
        raise BaiduError(f"create failed: {created}")
    return {"ok": True, "rapid": False, "path": path, "create": created, "size": size}
