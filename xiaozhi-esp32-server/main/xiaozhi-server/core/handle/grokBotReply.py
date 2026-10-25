"""Bot replies as local files: one `.pending.json` per request, the Bot (or the HTTP callback) writes
the `.json` result next to it. core/gateway/agents/grok_webhook.py hands them to the gateway."""
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from pathlib import Path


# Bot replies usually take longer than the idle timeout, so a session with an
# outstanding request stays open for up to this long.
REPLY_WAIT_SECONDS = 300
# A posted reply is accepted this long after the request.
REPLY_TOKEN_SECONDS = 24 * 3600


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def prepare_reply(directory, request_id, device, token=None):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Bot reply directory must be absolute")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = directory / (request_id + ".pending.json")
    metadata = {"request_id": request_id, "device": device, "created": time.time()}
    if token:
        # Only the hash is kept, so the reply directory never holds a usable token.
        metadata["token_sha256"] = _token_hash(token)
    with pending.open("x", encoding="utf-8") as file:
        pending.chmod(0o600)
        json.dump(metadata, file)
    return pending, directory / (request_id + ".json")


def accept_reply(directory, request_id, token, text):
    """Store a reply posted over HTTP; returns an HTTP status code.

    The posted reply becomes the same result file the Bot used to write locally,
    so delivery, retries and the waiting UI stay unchanged.
    """
    if not isinstance(request_id, str) or not re.fullmatch(r"ESP32-[0-9a-f]{32}", request_id):
        return 400
    if not isinstance(token, str) or not token or not isinstance(text, str):
        return 400
    if not text.strip() or len(text) > 8000:
        return 400
    directory = Path(directory)
    pending = directory / (request_id + ".pending.json")
    try:
        if pending.is_symlink() or pending.stat().st_size > 4096:
            return 404
        metadata = json.loads(pending.read_text(encoding="utf-8"))
        expected = metadata.get("token_sha256")
        if not isinstance(expected, str) or not hmac.compare_digest(expected, _token_hash(token)):
            return 403
        # Late replies are still delivered (timed-out requests are kept), within a day.
        if time.time() - float(metadata["created"]) > REPLY_TOKEN_SECONDS:
            return 404
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 404
    result = directory / (request_id + ".json")
    if result.exists() or result.is_symlink():
        return 409
    temp = directory / f".{request_id}.{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"request_id": request_id, "text": text.strip()}, file, ensure_ascii=False)
        temp.rename(result)
    except OSError:
        temp.unlink(missing_ok=True)
        return 500
    return 200


def _metadata(path, request_id, device):
    """The request record (.pending.json or .sent.json) when it belongs to this device, else None."""
    if not re.fullmatch(r"ESP32-[0-9a-f]{32}", request_id) or path.is_symlink():
        return None
    if path.stat().st_size > 4096:
        return None
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("request_id") != request_id or metadata.get("device") != device:
        return None
    return metadata


def _result_text(reply, request_id):
    """The bounded text of a result file written for this request, else None."""
    if reply.is_symlink() or reply.stat().st_size > 65536:
        return None
    data = json.loads(reply.read_text(encoding="utf-8"))
    text = data.get("text")
    if data.get("request_id") != request_id or not isinstance(text, str):
        return None
    if not text.strip() or len(text) > 8000:
        return None
    reply.chmod(0o600)
    return text.strip()


def read_reply(pending, device):
    """Only accept a bounded reply for a request created for this device."""
    try:
        request_id = pending.name.removesuffix(".pending.json")
        metadata = _metadata(pending, request_id, device)
        if metadata is None:
            return None
        text = _result_text(pending.with_name(request_id + ".json"), request_id)
        return None if text is None else (request_id, text, metadata.get("created"))
    except (OSError, ValueError, AttributeError, TypeError):
        # The Bot may still be writing. Invalid/incomplete files are not displayed.
        return None


# More from the Bot after its first answer to a request (a correction, or what another Bot it
# passed the task to replied): <request id>.more-<n>.json, same format. 2026-10-25 实机: the
# first answer said it could not see the other Bots, the correction stayed in the Grok chat.
FOLLOW_UP = re.compile(r"(ESP32-[0-9a-f]{32})\.more-([0-9]{1,2})\.json")


def next_follow_up(directory, device, max_age=REPLY_TOKEN_SECONDS, now=None):
    """The oldest unsaid follow-up for this device as (file, request id, text), else None.

    Only for requests whose first answer was already said (.sent.json) within max_age seconds.
    """
    now = time.time() if now is None else now
    directory = Path(directory)
    for path in sorted(directory.glob("ESP32-*.more-*.json"), key=lambda p: p.stat().st_mtime):
        match = FOLLOW_UP.fullmatch(path.name)
        if not match:
            continue
        request_id = match.group(1)
        try:
            metadata = _metadata(directory / (request_id + ".sent.json"), request_id, device)
            if metadata is None or not 0 <= now - float(metadata["created"]) < max_age:
                continue
            text = _result_text(path, request_id)
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            continue
        if text is not None:
            return path, request_id, text
    return None


def mark_follow_up_sent(path):
    path.rename(path.with_name(path.name.removesuffix(".json") + ".sent.json"))


def next_reply(directory, device):
    """The oldest readable reply for this device as (pending file, request id, text, created), else None."""
    for pending in sorted(Path(directory).glob("ESP32-*.pending.json"), key=lambda p: p.stat().st_mtime):
        reply = read_reply(pending, device)
        if reply is not None:
            return (pending, *reply)
    return None


def mark_sent(pending, request_id):
    pending.rename(pending.with_name(request_id + ".sent.json"))


def latest_request(directory, device, wait_seconds, now=None):
    """When this device's newest request without a delivered reply was sent, if within wait_seconds; else 0."""
    now = time.time() if now is None else now
    latest = 0
    for pending in Path(directory).glob("ESP32-*.pending.json"):
        try:
            if pending.is_symlink() or pending.stat().st_size > 4096:
                continue
            metadata = json.loads(pending.read_text(encoding="utf-8"))
            created = float(metadata["created"])
            if metadata.get("device") == device and 0 <= now - created < wait_seconds:
                latest = max(latest, created)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return latest


def waiting_for_reply(directory, device, wait_seconds, now=None):
    """True while a recent request from this device has no delivered reply."""
    return bool(latest_request(directory, device, wait_seconds, now))
