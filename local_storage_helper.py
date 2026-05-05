# coding: utf-8
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
from datetime import datetime

import streamlit as st
from streamlit_local_storage import LocalStorage

_LS_INIT_KEY = "quiz_ls_init"
_DATA_KEY = "quiz_app_data"
_SESSION_KEY = "_app_data"


def _default_data() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "users": [],
        "last_user": "",
        "stats": {},
        "all_tags": [],
        "question_tags": {},
        "default_tags": [],
        "default_question_tags": {},
        "system_tags": [],
        "system_question_tags": {},
        "share_emails": {},
        "daily_stats": {},
        # quiz_sessions stores per-quiz session records per user: {user: [ {date, count, seconds, ts}, ... ]}
        "quiz_sessions": {},
        "user_settings": {},
    }


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
    """Ensure app data is loaded into session_state. Call once at startup.

    LocalStorage はブラウザとの通信が非同期なため、最初のレンダリングでは
    データが空になることがある。2回目以降のレンダリングで実データが届いた
    タイミングで再ロードするように「暫定フラグ」を使う。
    """
    ls_has_data = ls.getItem(_DATA_KEY) is not None

    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = load_app_data(ls)
        if not ls_has_data:
            # LocalStorage がまだデータを返していない（初回レンダリング）。
            # 次のレンダリングで実データが届いたら再ロードするため暫定フラグを立てる。
            st.session_state["_ls_data_tentative"] = True
    elif st.session_state.get("_ls_data_tentative") and ls_has_data:
        # 暫定フラグが立っており、かつ LocalStorage に実データがある →
        # 前回は空で読み込んでいたので、ここで正しいデータを再ロードする。
        st.session_state[_SESSION_KEY] = load_app_data(ls)
        st.session_state["_ls_data_tentative"] = False


def save_app_data(ls: LocalStorage) -> None:
    """Persist current app data from session_state to browser localStorage.

    Call once at the end of each page render.
    """
    data = st.session_state.get(_SESSION_KEY)
    if data is None:
        return
    # Ensure deterministic ordering for stable serialization in tests
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    # Persist into browser localStorage under the single application data key.
    # Note: streamlit-local-storage's setItem expects (key, value). Passing
    # an extra keyword caused the value to be stored in a different internal
    # slot and thus not retrievable by getItem(). Use the simple form.
    ls.setItem(_DATA_KEY, serialized)


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
    name = user_name.strip()
    if not name:
        return
    data = _get_data()
    users = data.setdefault("users", [])
    # avoid duplicates
    if any(u.get("user_name") == name for u in users):
        return
    users.append({"user_name": name})
    data["users"] = users
    _set_data(data)


def record_quiz_session(user_name: str, seconds: int, count: int, date: str | None = None) -> None:
    """Record a quiz session for the user.

    Stores an entry with fields: date (YYYY-MM-DD), count (number of questions), seconds (duration), ts (iso timestamp).
    """
    if not user_name:
        return
    try:
        if date:
            datetime.fromisoformat(date)
            day_key = date
        else:
            day_key = datetime.now().strftime("%Y-%m-%d")
    except Exception:
        day_key = datetime.now().strftime("%Y-%m-%d")

    data = _get_data()
    sessions = data.setdefault("quiz_sessions", {})
    user_sessions = sessions.setdefault(user_name, [])
    entry = {"date": day_key, "count": int(count), "seconds": int(seconds), "ts": datetime.now().isoformat()}
    user_sessions.append(entry)
    data["quiz_sessions"] = sessions
    _set_data(data)


def get_fastest_time_for_count(user_name: str, count: int) -> int | None:
    """Return the minimum seconds for quiz sessions with given *count* for *user_name*.

    Returns None if no matching sessions.
    """
    if not user_name:
        return None
    data = _get_data()
    sessions = data.get("quiz_sessions", {}).get(user_name, [])
    vals = [int(s.get("seconds", 0)) for s in sessions if int(s.get("count", 0)) == int(count)]
    if not vals:
        return None
    return min(vals)


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
    # share_emailsから削除
    share_emails = data.get("share_emails", {})
    if user_name in share_emails:
        del share_emails[user_name]
        data["share_emails"] = share_emails
    # last_userが該当ユーザーなら空に
    if data.get("last_user") == user_name:
        data["last_user"] = ""
    _set_data(data)


# ── Share email management ───────────────────────────────────


def get_share_emails(user_name: str) -> list[str]:
    """Return the list of share email addresses for *user_name*."""
    if not user_name:
        return []
    return list(_get_data().get("share_emails", {}).get(user_name, []))


def set_share_emails(user_name: str, emails: list[str]) -> None:
    """Overwrite the share email list for *user_name*."""
    if not user_name:
        return
    data = _get_data()
    share_emails = data.setdefault("share_emails", {})
    share_emails[user_name] = emails
    _set_data(data)


# ── Per-user settings ─────────────────────────────────────────


def get_user_settings(user_name: str) -> dict:
    """Return per-user settings dict (or {})."""
    if not user_name:
        return {}
    us = _get_data().get("user_settings", {})
    # Exact match first
    if user_name in us:
        return dict(us[user_name] or {})
    # Fallback: case-insensitive/whitespace-insensitive match to be robust
    norm = user_name.strip().casefold()
    for k, v in us.items():
        try:
            if str(k).strip().casefold() == norm:
                return dict(v or {})
        except Exception:
            continue
    return {}


def set_user_settings(user_name: str, settings: dict) -> None:
    """Overwrite settings for a given user.

    Settings is a plain dict and will be stored under data['user_settings'][user_name].
    """
    if not user_name:
        return
    data = _get_data()
    us = data.setdefault("user_settings", {})
    # Try to find an existing key that matches user_name case-insensitively
    target_key = None
    norm = user_name.strip().casefold()
    for k in list(us.keys()):
        try:
            if str(k).strip().casefold() == norm:
                target_key = k
                break
        except Exception:
            continue
    if target_key is None:
        target_key = user_name
    # store a shallow copy to avoid accidental cross-ref
    us[target_key] = dict(settings or {})
    _set_data(data)


# ── Answer statistics ────────────────────────────────────────────


def get_question_stats(user_name: str) -> dict[int, tuple[int, int, int, int]]:
    """Return per-question stats for *user_name*.

    Returns ``{question_id: (total_asked, total_correct, total_incorrect, streak)}``.
    streak = current consecutive correct answers count.
    """
    if not user_name:
        return {}
    user_stats = _get_data().get("stats", {}).get(user_name, {})
    result: dict[int, tuple[int, int, int, int]] = {}
    for k, v in user_stats.items():
        try:
            qid = int(k)
            streak = int(v[3]) if len(v) > 3 else 0
            result[qid] = (int(v[0]), int(v[1]), int(v[2]), streak)
        except (ValueError, IndexError, TypeError):
            continue
    return result


# 日別の学習履歴を記録する
def record_answer(question_id: int, is_correct_answer: bool, user_name: str) -> None:
    """Record one answer and update cumulative stats. Also record daily history."""
    if not user_name:
        return
    data = _get_data()
    stats = data.setdefault("stats", {})
    user_stats = stats.setdefault(user_name, {})

    qid = str(question_id)
    prev = user_stats.get(qid, [0, 0, 0, 0])
    asked = int(prev[0]) + 1
    correct = int(prev[1]) + (1 if is_correct_answer else 0)
    incorrect = int(prev[2]) + (0 if is_correct_answer else 1)
    streak = (int(prev[3]) if len(prev) > 3 else 0) + 1 if is_correct_answer else 0
    user_stats[qid] = [asked, correct, incorrect, streak]

    # --- 日別履歴 ---
    # 一時的に学習日をオーバーライドする場合がある (例: カレンダーから過去/未来日の学習を開始)
    override = None
    try:
        override = st.session_state.get("override_record_date") if "override_record_date" in st.session_state else None
    except Exception:
        override = None
    if override and isinstance(override, str):
        try:
            # 形式 YYYY-MM-DD を期待
            today = datetime.fromisoformat(override).strftime("%Y-%m-%d")
        except Exception:
            today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
    daily = data.setdefault("daily_stats", {})
    user_daily = daily.setdefault(user_name, {})
    day = user_daily.setdefault(today, {"total": 0, "correct": 0, "seconds": 0})
    day["total"] += 1
    if is_correct_answer:
        day["correct"] += 1

    _set_data(data)


def add_daily_study_seconds(user_name: str, seconds: int, date: str | None = None) -> None:
    """Add study seconds to the given user's daily_stats for *date* (YYYY-MM-DD).

    If *date* is None, today's date is used. Seconds is added cumulatively.
    """
    if not user_name:
        return
    try:
        if date:
            # validate format roughly
            datetime.fromisoformat(date)
            day_key = date
        else:
            day_key = datetime.now().strftime("%Y-%m-%d")
    except Exception:
        day_key = datetime.now().strftime("%Y-%m-%d")

    data = _get_data()
    daily = data.setdefault("daily_stats", {})
    user_daily = daily.setdefault(user_name, {})
    day = user_daily.setdefault(day_key, {"total": 0, "correct": 0, "seconds": 0})
    try:
        day["seconds"] = int(day.get("seconds", 0)) + int(seconds)
    except Exception:
        day["seconds"] = int(seconds)
    _set_data(data)


def get_daily_stats(user_name: str) -> dict:
    """Return {date: {total, correct}} for the user."""
    if not user_name:
        return {}
    data = _get_data()
    return dict(data.get("daily_stats", {}).get(user_name, {}))

def get_learning_streak(user_name: str) -> int:
    """ユーザーの連続学習日数（今日を含む）を返す。"""
    daily = get_daily_stats(user_name)
    if not daily:
        return 0
    # 「学習日」とみなすのは出題数が閾値以上の日のみ
    LEARNING_DAY_THRESHOLD = 10
    learned_dates = [d for d, v in daily.items() if isinstance(v, dict) and int(v.get("total", 0)) >= LEARNING_DAY_THRESHOLD]
    if not learned_dates:
        return 0
    dates = sorted(learned_dates, reverse=True)
    streak = 0
    today = datetime.now().date()
    # 日付文字列をdate型に変換
    date_objs = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    for i, d in enumerate(date_objs):
        if i == 0:
            # 今日 or 昨日から始まっていればカウント
            if (today - d).days > 1:
                break
            streak += 1
        else:
            prev = date_objs[i-1]
            if (prev - d).days == 1:
                streak += 1
            else:
                break
    return streak


def reset_user_stats(user_name: str) -> None:
    """Clear all learning records for *user_name*.

    This removes:
    - 累積問題別スタッツ (data["stats"][user_name])
    - 日別学習統計 (data["daily_stats"][user_name])

    Note: ユーザーアカウント自体（users リスト）やタグ等の設定は残します。
    """
    if not user_name:
        return
    data = _get_data()
    # Normalize function for robust matching (trim + casefold)
    def _norm(n: str) -> str:
        try:
            return n.strip().casefold()
        except Exception:
            return str(n).strip().casefold()

    target_norm = _norm(user_name)

    # 累積スタッツを削除（キーが厳密一致しないケースにも対応）
    stats = data.get("stats", {})
    keys_to_remove = [k for k in stats.keys() if _norm(str(k)) == target_norm]
    for k in keys_to_remove:
        stats.pop(k, None)

    # 日別学習履歴を削除（同様に正規化してマッチング）
    daily = data.get("daily_stats", {})
    keys_to_remove = [k for k in daily.keys() if _norm(str(k)) == target_norm]
    for k in keys_to_remove:
        daily.pop(k, None)

    # クイズセッション履歴（最速タイム等）を削除
    quiz_sessions = data.get("quiz_sessions", {})
    keys_to_remove = [k for k in quiz_sessions.keys() if _norm(str(k)) == target_norm]
    for k in keys_to_remove:
        quiz_sessions.pop(k, None)

    # 共有メールも削除
    share_emails = data.get("share_emails", {})
    keys_to_remove = [k for k in share_emails.keys() if _norm(str(k)) == target_norm]
    for k in keys_to_remove:
        share_emails.pop(k, None)

    _set_data(data)


# ── Tag management ────────────────────────────────────────────


def get_all_tags() -> list[str]:
    """Return the list of all tags."""
    return list(_get_data().get("all_tags", []))


def set_all_tags(tags: list[str]) -> None:
    """Overwrite the full tag list."""
    # normalize: strip, remove empty, dedupe while preserving order
    norm: list[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s:
            continue
        if s not in norm:
            norm.append(s)
    data = _get_data()
    data["all_tags"] = norm
    _set_data(data)


def get_question_tags() -> dict[str, list[str]]:
    """Return {question_id_str: [tag, ...]} mapping."""
    return dict(_get_data().get("question_tags", {}))


def set_question_tags(question_tags: dict[str, list[str]]) -> None:
    """Overwrite the full question-tags mapping."""
    # normalize keys to strings and tag lists to stripped unique strings
    norm: dict[str, list[str]] = {}
    for k, v in (question_tags or {}).items():
        try:
            key = str(int(k))  # ensure numeric-like keys stay numeric string
        except Exception:
            key = str(k)
        tags_list: list[str] = []
        for t in (v or []):
            if not isinstance(t, str):
                continue
            s = t.strip()
            if not s:
                continue
            if s not in tags_list:
                tags_list.append(s)
        if tags_list:
            norm[key] = tags_list
    data = _get_data()
    data["question_tags"] = norm
    _set_data(data)


# ── Default tag management (from CSV) ────────────────────────

def get_default_tags() -> list[str]:
    """Return the list of default tags (from CSV)."""
    return list(_get_data().get("default_tags", []))


def set_default_tags(tags: list[str]) -> None:
    """Overwrite the default tag list."""
    norm: list[str] = []
    for t in tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s:
            continue
        if s not in norm:
            norm.append(s)
    data = _get_data()
    data["default_tags"] = norm
    _set_data(data)


def get_default_question_tags() -> dict[str, list[str]]:
    """Return {question_id_str: [tag, ...]} mapping for default tags."""
    return dict(_get_data().get("default_question_tags", {}))


def set_default_question_tags(question_tags: dict[str, list[str]]) -> None:
    """Overwrite the default question-tags mapping."""
    # reuse normalization logic
    norm: dict[str, list[str]] = {}
    for k, v in (question_tags or {}).items():
        try:
            key = str(int(k))
        except Exception:
            key = str(k)
        tags_list: list[str] = []
        for t in (v or []):
            if not isinstance(t, str):
                continue
            s = t.strip()
            if not s:
                continue
            if s not in tags_list:
                tags_list.append(s)
        if tags_list:
            norm[key] = tags_list
    data = _get_data()
    data["default_question_tags"] = norm
    _set_data(data)


# ── System tag management ────────────────────────────────────

def get_system_tags() -> list[str]:
    """Return the list of system tags."""
    return list(_get_data().get("system_tags", []))


def set_system_tags(tags: list[str]) -> None:
    """Overwrite the system tag list."""
    norm: list[str] = []
    for t in tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s:
            continue
        if s not in norm:
            norm.append(s)
    data = _get_data()
    data["system_tags"] = norm
    _set_data(data)


def get_system_question_tags() -> dict[str, list[str]]:
    """Return {question_id_str: [tag, ...]} mapping for system tags."""
    return dict(_get_data().get("system_question_tags", {}))


def set_system_question_tags(question_tags: dict[str, list[str]]) -> None:
    """Overwrite the system question-tags mapping."""
    norm: dict[str, list[str]] = {}
    for k, v in (question_tags or {}).items():
        try:
            key = str(int(k))
        except Exception:
            key = str(k)
        tags_list: list[str] = []
        for t in (v or []):
            if not isinstance(t, str):
                continue
            s = t.strip()
            if not s:
                continue
            if s not in tags_list:
                tags_list.append(s)
        if tags_list:
            norm[key] = tags_list
    data = _get_data()
    data["system_question_tags"] = norm
    _set_data(data)

