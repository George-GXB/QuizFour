"""Manage quiz user data and answer statistics in browser localStorage.

Data structure in localStorage (single key 'quiz_app_data'):
{
    "users": [{"user_name": "george"}, ...],
    "last_user": "george",
    "stats": {
        "george": {
            "<question_id>": [total_asked, total_correct, total_incorrect],
            ...
        },
        ...
    }
}

Question data (questions, imported_files) stays in server-side SQLite.
"""
from __future__ import annotations

import json
from typing import Any

import streamlit as st
from streamlit_local_storage import LocalStorage

_LS_INIT_KEY = "quiz_ls_init"
_DATA_KEY = "quiz_app_data"
_SESSION_KEY = "_app_data"


def _default_data() -> dict[str, Any]:
    return {"users": [], "last_user": "", "stats": {}, "all_tags": [], "question_tags": {}}


def init_local_storage() -> LocalStorage:
    """Initialize LocalStorage component (renders once per session)."""
    return LocalStorage(key=_LS_INIT_KEY)


def load_app_data(ls: LocalStorage) -> dict[str, Any]:
    """Load app data from browser localStorage into a Python dict."""
    raw = ls.getItem(_DATA_KEY)
    if raw is None:
        return _default_data()
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return _default_data()
    elif isinstance(raw, dict):
        data = raw
    else:
        return _default_data()
    # Ensure all top-level keys exist
    defaults = _default_data()
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    return data


def ensure_loaded(ls: LocalStorage) -> None:
    """Ensure app data is loaded into session_state. Call once at startup."""
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = load_app_data(ls)


def save_app_data(ls: LocalStorage) -> None:
    """Persist current app data from session_state to browser localStorage.

    Call once at the end of each page render.
    """
    data = st.session_state.get(_SESSION_KEY)
    if data is None:
        return
    serialized = json.dumps(data, ensure_ascii=False)
    # key must be a stable unique string so the component tree is consistent
    ls.setItem(_DATA_KEY, serialized, key="ls_persist_data")


def _get_data() -> dict[str, Any]:
    """Get current app data dict from session_state."""
    return st.session_state.get(_SESSION_KEY, _default_data())


def _set_data(data: dict[str, Any]) -> None:
    """Update app data in session_state (will be persisted on next save)."""
    st.session_state[_SESSION_KEY] = data


# ── User management ──────────────────────────────────────────────


def get_registered_users() -> list[dict[str, str]]:
    """Return list of registered users: [{"user_name": ...}, ...]."""
    return list(_get_data().get("users", []))


def register_user(user_name: str) -> None:
    """Register a new user (stored in localStorage)."""
    data = _get_data()
    data.setdefault("users", []).append(
        {"user_name": user_name}
    )
    _set_data(data)


def user_exists(user_name: str) -> bool:
    """Check whether *user_name* is already registered."""
    return any(u["user_name"] == user_name for u in get_registered_users())


def get_last_user() -> str:
    """Return the last selected user name."""
    return _get_data().get("last_user", "")


def set_last_user(user_name: str) -> None:
    """Remember *user_name* as the last selected user."""
    data = _get_data()
    data["last_user"] = user_name
    _set_data(data)


def delete_user(user_name: str) -> None:
    """Delete a user and all their stats from localStorage."""
    data = _get_data()
    # usersリストから削除
    users = data.get("users", [])
    data["users"] = [u for u in users if u.get("user_name") != user_name]
    # statsから削除
    stats = data.get("stats", {})
    if user_name in stats:
        del stats[user_name]
    # last_userが該当ユーザーなら空に
    if data.get("last_user") == user_name:
        data["last_user"] = ""
    _set_data(data)


# ── Answer statistics ────────────────────────────────────────────


def get_question_stats(user_name: str) -> dict[int, tuple[int, int, int]]:
    """Return per-question stats for *user_name*.

    Returns ``{question_id: (total_asked, total_correct, total_incorrect)}``.
    """
    if not user_name:
        return {}
    user_stats = _get_data().get("stats", {}).get(user_name, {})
    result: dict[int, tuple[int, int, int]] = {}
    for k, v in user_stats.items():
        try:
            qid = int(k)
            result[qid] = (int(v[0]), int(v[1]), int(v[2]))
        except (ValueError, IndexError, TypeError):
            continue
    return result


def record_answer(question_id: int, is_correct_answer: bool, user_name: str) -> None:
    """Record one answer and update cumulative stats."""
    if not user_name:
        return
    data = _get_data()
    stats = data.setdefault("stats", {})
    user_stats = stats.setdefault(user_name, {})

    qid = str(question_id)
    prev = user_stats.get(qid, [0, 0, 0])
    asked = int(prev[0]) + 1
    correct = int(prev[1]) + (1 if is_correct_answer else 0)
    incorrect = int(prev[2]) + (0 if is_correct_answer else 1)
    user_stats[qid] = [asked, correct, incorrect]
    _set_data(data)


def reset_user_stats(user_name: str) -> None:
    """Clear all answer stats for *user_name*."""
    if not user_name:
        return
    data = _get_data()
    stats = data.get("stats", {})
    if user_name in stats:
        del stats[user_name]
    _set_data(data)


# ── Tag management ────────────────────────────────────────────


def get_all_tags() -> list[str]:
    """Return the list of all tags."""
    return list(_get_data().get("all_tags", []))


def set_all_tags(tags: list[str]) -> None:
    """Overwrite the full tag list."""
    data = _get_data()
    data["all_tags"] = tags
    _set_data(data)


def get_question_tags() -> dict[str, list[str]]:
    """Return {question_id_str: [tag, ...]} mapping."""
    return dict(_get_data().get("question_tags", {}))


def set_question_tags(question_tags: dict[str, list[str]]) -> None:
    """Overwrite the full question-tags mapping."""
    data = _get_data()
    data["question_tags"] = question_tags
    _set_data(data)

