# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import time
import types
from urllib.parse import urlsplit

from huggingface_hub import HfApi, get_token, login as hf_login, whoami
from huggingface_hub.errors import HfHubHTTPError

logger = logging.getLogger(__name__)

LOGIN_COMMAND = "hf auth login"

_PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


def _drop_proxies_httpx_cannot_use() -> None:
    """Drop proxy env vars that make every Hub call raise before it is sent.

    huggingface_hub 2.x uses httpx, which parses the proxy environment itself.
    A shell that exports `ALL_PROXY=socks://host:port` (common with v2rayN-style
    clients) makes httpx raise `ValueError: Unknown scheme for proxy URL`, and
    socks4/5 proxies need the optional `socksio` package. Neither case can ever
    succeed, so remove just those variables and leave HTTP(S)_PROXY untouched.
    """
    try:
        import socksio  # noqa: F401
    except ImportError:
        socksio = None
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if not value:
            continue
        scheme = urlsplit(value).scheme.lower()
        if not scheme.startswith("socks"):
            continue
        if socksio is None or scheme == "socks":
            os.environ.pop(key, None)
            logger.info(
                "Ignoring %s=%s: proxy scheme unsupported by huggingface_hub (httpx)",
                key,
                value,
            )


_drop_proxies_httpx_cannot_use()

# /whoami-v2 is heavily rate-limited (security). Share one HfApi across the
# app so its in-process whoami cache (cache=True) actually hits — otherwise
# polling endpoints like /jobs/hub would burn the rate limit on every tick.
_WHOAMI_API = HfApi()

# HfApi.run_job() internally calls self.whoami(token=token) WITHOUT cache=True
# to resolve the namespace, which burns the /whoami-v2 rate limit on every
# job submission. Bind a shim on this shared instance that defaults cache=True
# so every HfApi method on _WHOAMI_API (run_job, inspect_job's lazy whoami,
# etc.) hits the in-process cache once a token has been validated.
_orig_whoami = HfApi.whoami

# Newer huggingface_hub removed the `cache` kwarg from HfApi.whoami, so we keep
# our own TTL cache here and never forward `cache` to the underlying call.
_WHOAMI_CACHE: dict[str, tuple[float, dict]] = {}
_WHOAMI_TTL = 300.0


def _whoami_default_cache(self, token=None, *, cache=True):
    key = token if isinstance(token, str) else (get_token() or "")
    if cache and key:
        hit = _WHOAMI_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < _WHOAMI_TTL:
            return hit[1]
    info = _orig_whoami(self, token=token)
    if key:
        _WHOAMI_CACHE[key] = (time.monotonic(), info)
    return info


_WHOAMI_API.whoami = types.MethodType(_whoami_default_cache, _WHOAMI_API)


def cached_whoami() -> dict | None:
    """Return cached whoami() for the active HF token, or None if no token.

    Swallows transport errors and returns None — callers treat that as
    "unauthenticated" so the UI degrades gracefully instead of 500ing.
    """
    token = get_token()
    if not token:
        return None
    try:
        return _WHOAMI_API.whoami(token=token, cache=True)
    except Exception as exc:
        logger.info("whoami failed: %s", exc)
        return None


def shared_hf_api() -> HfApi:
    """The shared HfApi used for whoami caching. Reuse it for non-whoami
    calls in the same handler so they share connection pooling, but it's
    the whoami cache that matters."""
    return _WHOAMI_API


def invalidate_whoami_cache() -> None:
    """Drop the cached whoami() result. Call after a token rotation so the
    next caller re-validates against the Hub."""
    _WHOAMI_CACHE.clear()
    legacy = getattr(_WHOAMI_API, "_whoami_cache", None)
    if legacy is not None:
        legacy.clear()


def handle_hf_auth_status() -> dict:
    try:
        info = whoami()
        return {
            "authenticated": True,
            "username": info["name"],
            "orgs": [o["name"] for o in info.get("orgs", [])],
            "login_command": LOGIN_COMMAND,
        }
    except Exception as e:
        # Never surface a transport/config failure as a 500: the UI turns that
        # into "HF CLI not configured", which is wrong advice. Catch everything
        # (httpx raises ValueError for bad proxy schemes, not OSError) and let
        # the caller treat it as unauthenticated.
        logger.info(f"HF auth check: not authenticated ({type(e).__name__}: {e})")
        return {
            "authenticated": False,
            "username": None,
            "orgs": [],
            "login_command": LOGIN_COMMAND,
        }


def handle_hf_login(token: str) -> dict:
    """Validate and persist an HF token pasted from the UI.

    whoami() validates the token; on success, huggingface_hub.login() writes
    it to ~/.cache/huggingface/token (same as `hf auth login`). Subsequent
    get_token() calls then pick it up automatically.
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("Token must not be empty")
    try:
        info = whoami(token=token)
    except HfHubHTTPError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Cannot reach Hugging Face: {exc}") from exc
    hf_login(token=token, add_to_git_credential=False)
    # The cached whoami was keyed by the previous token (if any); drop it so
    # the next caller validates against the new one.
    invalidate_whoami_cache()
    return {
        "authenticated": True,
        "username": info["name"],
        "orgs": [o["name"] for o in info.get("orgs", [])],
        "login_command": LOGIN_COMMAND,
    }
