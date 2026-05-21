import json
import logging

from . import cache_keys
from .config import FALLBACK_USER_AGENT, upstream_host
from .network import build_api_url, http_get
from .platform import resolve_retroarch_cfg_search
from .retroarch_cfg import (
    load_retroarch_password_credentials_any,
    load_retroarch_token_credentials_any,
)
from .storage import Storage
from .utils import proxy_user_agent

LOGGER = logging.getLogger("raofflineproxy")


def resolve_credentials(
    storage: Storage,
    config_data: dict | None = None,
    user_agent: str = FALLBACK_USER_AGENT,
) -> dict | None:
    config_data = config_data or {}
    search_paths = resolve_retroarch_cfg_search(config_data)
    token_credentials = load_retroarch_token_credentials_any(search_paths)
    if token_credentials is not None:
        return cache_token_credentials(storage, token_credentials)

    cached = storage.load_login_credentials()
    if cached is not None:
        return cached

    password_credentials = load_retroarch_password_credentials_any(search_paths)
    if password_credentials is None:
        return None

    return login_and_cache_token(storage, config_data, password_credentials, user_agent)


def cache_token_credentials(storage: Storage, credentials: dict) -> dict | None:
    user = credentials.get("user")
    token = credentials.get("token")
    if not user or not token:
        return None

    body = json.dumps({"Success": True, "User": user, "Token": token})
    storage.upsert_cache(cache_keys.login(user), body)
    return {"user": user, "token": token}


def import_saved_login(storage: Storage, config_data: dict | None = None) -> dict | None:
    config_data = config_data or {}
    credentials = load_retroarch_token_credentials_any(
        resolve_retroarch_cfg_search(config_data)
    )
    if credentials is None:
        return None

    user = credentials["user"]
    token = credentials["token"]
    if storage.get_cache(cache_keys.login(user)) is None:
        storage.upsert_cache(
            cache_keys.login(user),
            json.dumps(
                {
                    "Success": True,
                    "User": user,
                    "Token": token,
                    "Score": 0,
                    "SoftcoreScore": 0,
                    "Messages": 0,
                },
                separators=(",", ":"),
            ),
        )
    return {"user": user, "token": token}


def login_and_cache_token(
    storage: Storage,
    config_data: dict,
    credentials: dict,
    user_agent: str,
) -> dict | None:
    url = build_api_url(
        upstream_host(config_data),
        "login2",
        {
            "u": credentials["user"],
            "p": credentials["password"],
        },
    )
    try:
        response_body = http_get(
            url, proxy_user_agent(user_agent or FALLBACK_USER_AGENT)
        )
        payload = json.loads(response_body)
    except Exception as exc:
        LOGGER.warning("login2 request failed: %s", exc)
        return None

    user = payload.get("User") or credentials["user"]
    token = payload.get("Token")
    if not payload.get("Success") or not user or not token:
        LOGGER.warning("login2 rejected credentials for user=%s", credentials["user"])
        return None

    storage.upsert_cache(cache_keys.login(user), response_body)
    return {"user": user, "token": token}
