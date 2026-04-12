from __future__ import annotations

from collections import defaultdict
import html
from pathlib import Path
import random
import re

import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

from quiz_logic import (
    Question,
    export_correct_answers_to_csvs,
    filter_questions,
    get_category_options,
    is_correct,
    limit_questions,
    load_question_stats,
    load_questions_from_db,
    record_answer_history,
    reload_db_from_csvs,
    reset_answer_history,
    sync_csvs_to_db,
    update_correct_index,
)

INPUT_DIR = Path(__file__).parent / "input"
DB_PATH = Path(__file__).parent / "quiz.db"
CONFIG_PATH = Path(__file__).parent / "config.yaml"

st.set_page_config(page_title="English Quiz", page_icon="📘", layout="centered")

# ── 認証設定の読み込み ────────────────────────────────
with open(CONFIG_PATH, encoding="utf-8") as _f:
    _config = yaml.load(_f, Loader=SafeLoader)

# name→nickname自動変換（後方互換）
usernames = _config.get("credentials", {}).get("usernames", {})
changed = False
for uname, uinfo in usernames.items():
    if "name" in uinfo:
        uinfo["nickname"] = uinfo.pop("name")
        changed = True
if changed:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(_config, f, default_flow_style=False, allow_unicode=True)

authenticator = stauth.Authenticate(
    _config["credentials"],
    _config["cookie"]["name"],
    _config["cookie"]["key"],
    _config["cookie"]["expiry_days"],
)


def _save_config() -> None:
    """config.yaml にユーザー情報の変更を書き戻す。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(_config, f, default_flow_style=False, allow_unicode=True)


def load_questions() -> list[Question]:
    sync_csvs_to_db(INPUT_DIR, DB_PATH)
    return load_questions_from_db(DB_PATH)


def init_state() -> None:
    defaults = {
        "stage": "login",
        "user_name": "",
        "quiz_questions": [],
        "current_index": 0,
        "correct_count": 0,
        "answered": False,
        "selected_index": None,
        "show_japanese": False,
        "selected_category_values": [],
        "reload_notice": "",
        "answer_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def restart() -> None:
    st.session_state.stage = "setup"
    st.session_state.quiz_questions = []
    st.session_state.current_index = 0
    st.session_state.correct_count = 0
    st.session_state.answered = False
    st.session_state.selected_index = None
    st.session_state.show_japanese = False
    st.session_state.selected_category_values = []
    st.session_state.answer_history = []


def start_quiz(questions: list[Question], show_japanese: bool) -> None:
    st.session_state.stage = "quiz"
    st.session_state.quiz_questions = questions
    st.session_state.current_index = 0
    st.session_state.correct_count = 0
    st.session_state.answered = False
    st.session_state.selected_index = None
    st.session_state.show_japanese = show_japanese
    st.session_state.answer_history = []


def _toggle_selection(state_key: str, value: str) -> None:
    current_values = list(st.session_state.get(state_key, []))
    if value in current_values:
        current_values = [item for item in current_values if item != value]
    else:
        current_values.append(value)
    st.session_state[state_key] = current_values


def _clear_selection(state_key: str) -> None:
    st.session_state[state_key] = []


def _answer_question(choice_index: int) -> None:
    if st.session_state.answered:
        return

    st.session_state.selected_index = choice_index
    st.session_state.answered = True

    questions = st.session_state.quiz_questions
    index = st.session_state.current_index
    if not (0 <= index < len(questions)):
        return

    current_question = questions[index]
    answer_is_correct = is_correct(current_question, choice_index)
    if answer_is_correct:
        st.session_state.correct_count += 1

    try:
        record_answer_history(DB_PATH, current_question.id, answer_is_correct, st.session_state.get("user_name", ""))
    except Exception as exc:
        st.session_state["record_error"] = f"履歴記録に失敗しました: {exc}"

    choices = [current_question.choice1, current_question.choice2, current_question.choice3, current_question.choice4]
    st.session_state.answer_history.append(
        {
            "english": current_question.english or "(No English text)",
            "is_correct": answer_is_correct,
            "selected_index": choice_index,
            "correct_index": current_question.answer,
            "correct_text": choices[current_question.answer - 1],
        }
    )


def _group_key_and_index(option: str) -> tuple[str, int | None]:
    # 例: 不定詞1 -> (不定詞, 1)
    match = re.match(r"^(.*?)(\d+)$", option.strip())
    if not match:
        return option.strip(), None
    return match.group(1).strip(), int(match.group(2))


def _group_options_for_layout(options: list[str]) -> list[list[str]]:
    grouped: dict[str, list[tuple[int, str]]] = {}
    order: list[str] = []

    for option in options:
        group_key, number = _group_key_and_index(option)
        if group_key not in grouped:
            grouped[group_key] = []
            order.append(group_key)
        sort_key = number if number is not None else 10_000 + len(grouped[group_key])
        grouped[group_key].append((sort_key, option))

    rows: list[list[str]] = []
    for group_key in order:
        sorted_options = [option for _, option in sorted(grouped[group_key], key=lambda x: x[0])]
        rows.append(sorted_options)
    return rows


def _set_checkbox(state_key: str, option: str, checkbox_key: str) -> None:
    checked = st.session_state.get(checkbox_key, False)
    current = list(st.session_state.get(state_key, []))
    if checked and option not in current:
        current.append(option)
    elif not checked and option in current:
        current.remove(option)
    st.session_state[state_key] = current


def render_category_buttons(title: str, options: list[str], state_key: str, single_row: bool = False) -> None:
    if single_row:
        # タイトルとクリアボタンを同じ行に配置（ボタン群の上）
        col_title, col_clear = st.columns([6, 1])
        with col_title:
            st.write(title)
        with col_clear:
            st.button("クリア", key=f"{state_key}_clear", on_click=_clear_selection, args=(state_key,))
    else:
        st.write(title)

    if not options:
        st.caption("カテゴリがありません")
        return

    selected_values = set(st.session_state.get(state_key, []))
    grouped_rows = [options] if single_row else _group_options_for_layout(options)

    for row in grouped_rows:
        columns = st.columns(len(row))
        for idx, option in enumerate(row):
            is_selected = option in selected_values
            button_label = f"✓ {option}" if is_selected else option
            with columns[idx]:
                st.button(
                    button_label,
                    key=f"{state_key}_option_{option}",
                    type="primary" if is_selected else "secondary",
                    on_click=_toggle_selection,
                    args=(state_key, option),
                )

    if not single_row:
        st.button("選択をクリア", key=f"{state_key}_clear", on_click=_clear_selection, args=(state_key,))


def _build_recommended_pool(
    questions: list[Question], db_path: Path, count: int, user_name: str = ""
) -> tuple[list[Question], str]:
    """おすすめモード用の出題プールを作成する。

    - 未出題問題がある → その中からシャッフルして count 問選ぶ
    - 全問出題済み → 正解率が低い順に count 問選んでシャッフル
    戻り値: (シャッフル済み選択問題リスト, 説明メッセージ)
    """
    stats = load_question_stats(db_path, user_name)  # {question_id: (asked, correct, incorrect)}
    unanswered = [q for q in questions if q.id not in stats]

    if unanswered:
        selected = random.sample(unanswered, min(count, len(unanswered)))
        desc = f"未出題 {len(unanswered)} 問からシャッフルで {len(selected)} 問出題"
    else:
        def _rate(q: Question) -> float:
            asked, correct, _ = stats.get(q.id, (1, 0, 0))
            return correct / asked if asked > 0 else 0.0

        sorted_by_rate = sorted(questions, key=_rate)
        candidates = sorted_by_rate[:count]
        selected = random.sample(candidates, len(candidates))
        desc = f"全問出題済み・正解率低い {len(selected)} 問をシャッフルで出題"

    return selected, desc


def _reload_db_from_input() -> None:
    imported_count = reload_db_from_csvs(INPUT_DIR, DB_PATH)
    reloaded_questions = load_questions_from_db(DB_PATH)
    restart()
    st.session_state.reload_notice = (
        f"DBをクリアして再読込しました（取込CSV: {imported_count}件 / 問題数: {len(reloaded_questions)}件）"
    )


def _reset_answer_history_only() -> None:
    user_name = st.session_state.get("user_name", "")
    reset_answer_history(DB_PATH, user_name)
    st.session_state.reload_notice = f"「{user_name}」の学習成績をリセットしました。"


def render_setup(all_questions: list[Question]) -> None:
    st.title("English Quiz")
    user_name = st.session_state.get("user_name", "")
    # ニックネーム取得（空ならuser_nameをfallback）
    nickname = _config["credentials"]["usernames"].get(user_name, {}).get("nickname") or user_name
    # st.info(f"user_name: '{user_name}' (nickname: '{nickname}')")  # デバッグ用: 実際の値を表示

    header_col, logout_col = st.columns([5, 1])
    with header_col:
        if user_name:
            st.caption(f"👤 {user_name}（{nickname}）")
    with logout_col:
        authenticator.logout("ログアウト", location="main")

    # ログアウト後は login に戻す
    if not st.session_state.get("authentication_status"):
        st.session_state.stage = "login"
        st.session_state.user_name = ""
        st.rerun()

    notice = st.session_state.get("reload_notice", "")
    if notice:
        st.success(notice)
        st.session_state.reload_notice = ""

    st.markdown(
        """
        <style>
        .stButton > button {
            width: 100%;
            min-height: 48px;
            font-size: 1rem;
        }
        button[data-testid="baseButton-primary"] {
            min-height: 68px !important;
            font-size: 1.2rem !important;
            font-weight: bold !important;
            letter-spacing: 0.05em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    order_mode = st.radio(
        "出題モード",
        options=["おすすめ", "シャッフル", "順番通り", "順番通り（出題少ない順）"],
        horizontal=True,
        help="おすすめ：未出題問題を優先。全問済みなら正解率の低い問題をシャッフル出題",
    )
    show_japanese = st.checkbox("日本語を表示する", value=st.session_state.show_japanese)

    # カテゴリフィルタ（session_stateに保存済みの値で絞り込み）
    target_questions = filter_questions(
        all_questions,
        "all",
        st.session_state.selected_category_values,
        [],
    )

    count_mode = st.radio(
        "出題数",
        options=["10問", "20問", "30問", "50問", "全部"],
        horizontal=True,
    )
    preset_map = {"10問": 10, "20問": 20, "30問": 30, "50問": 50}
    question_count = preset_map.get(count_mode, len(target_questions))

    if order_mode == "おすすめ":
        user_name = st.session_state.get("user_name", "")
        quiz_questions, recommend_desc = _build_recommended_pool(target_questions, DB_PATH, question_count, user_name)
        st.info(f"🌟 おすすめ：{recommend_desc}（対象問題数: {len(target_questions)}）")
    else:
        if order_mode == "シャッフル":
            pool = random.sample(target_questions, len(target_questions))
            quiz_questions = limit_questions(pool, question_count)
            st.info(f"対象問題数: {len(target_questions)} / 出題数: {len(quiz_questions)}")
        elif order_mode == "順番通り（出題少ない順）":
            # 出題回数が少ない順にソート（同回数なら元の並び順を維持）
            user_name = st.session_state.get("user_name", "")
            stats = load_question_stats(DB_PATH, user_name)
            pool = sorted(
                target_questions,
                key=lambda q: stats.get(q.id, (0, 0, 0))[0],  # total_asked 昇順
            )
            quiz_questions = limit_questions(pool, question_count)
            unanswered_count = sum(1 for q in target_questions if q.id not in stats)
            st.info(f"対象問題数: {len(target_questions)} / 出題数: {len(quiz_questions)} / 未出題: {unanswered_count}問")
        else:
            pool = target_questions
            quiz_questions = limit_questions(pool, question_count)
            st.info(f"対象問題数: {len(target_questions)} / 出題数: {len(quiz_questions)}")
        if len(target_questions) < question_count:
            st.caption("対象問題が指定数より少ないため、ある問題のみ出題します。")

    if st.button("スタート", type="primary"):
        if not quiz_questions:
            st.error("条件に一致する問題がありません。条件を変更してください。")
            return
        start_quiz(quiz_questions, show_japanese)
        st.rerun()

    if st.button("これまでの成績リストを表示"):
        st.session_state.stage = "history"
        st.rerun()

    # ── カテゴリ範囲選択（一番下） ──────────────────────────
    category1_options, category2_options = get_category_options(all_questions)
    with st.expander("カテゴリ範囲を選ぶ", expanded=False):
        render_category_buttons("Category1（複数選択可）", category1_options, "selected_category_values", single_row=True)

    # ── パスワード変更 ──────────────────────────────────
    with st.expander("パスワードを変更する"):
        try:
            if authenticator.reset_password(
                st.session_state.get("username", ""),
                location="main",
            ):
                _save_config()
                st.success("パスワードを変更しました。")
        except Exception as exc:
            st.error(str(exc))

    st.divider()

    # georgeでログイン時のみDBクリアボタンを表示
    is_george = user_name.lower() == "george"

    if is_george:
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("学習成績をリセット"):
                st.session_state["confirm_reset"] = True
        # リセット確認ダイアログ
        if st.session_state.get("confirm_reset", False):
            current_user = st.session_state.get("user_name", "")
            st.warning("本当にいいですか？ もしよければユーザー名を入力してください。")
            confirm_name = st.text_input(
                "ユーザー名を入力",
                key="reset_confirm_input",
                placeholder=current_user,
            )
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("リセット実行", key="reset_exec_btn"):
                    if confirm_name.strip() == current_user:
                        try:
                            _reset_answer_history_only()
                        except Exception as exc:
                            st.error(f"成績リセットに失敗しました: {exc}")
                            st.session_state["confirm_reset"] = False
                            return
                        st.session_state["confirm_reset"] = False
                        st.rerun()
                    else:
                        st.error("ユーザー名が一致しません。リセットを中止しました。")
            with rc2:
                if st.button("キャンセル", key="reset_cancel_btn"):
                    st.session_state["confirm_reset"] = False
                    st.rerun()
        with col2:
            if st.button("DBクリア＆再読み込み"):
                try:
                    _reload_db_from_input()
                except Exception as exc:
                    st.error(f"DB再読み込みに失敗しました: {exc}")
                    return
                st.rerun()
        with col3:
            if st.button("正解データをCSVに反映"):
                try:
                    updated = export_correct_answers_to_csvs(INPUT_DIR, DB_PATH)
                    st.session_state.reload_notice = f"正解データをCSVに反映しました（更新ファイル: {updated}件）"
                except Exception as exc:
                    st.error(f"CSV反映に失敗しました: {exc}")
                    return
                st.rerun()
    else:
        col1 = st.columns(1)[0]
        with col1:
            if st.button("学習成績をリセット"):
                st.session_state["confirm_reset"] = True
        # リセット確認ダイアログ
        if st.session_state.get("confirm_reset", False):
            current_user = st.session_state.get("user_name", "")
            st.warning("本当にいいですか？ もしよければユーザー名を入力してください。")
            confirm_name = st.text_input(
                "ユーザー名を入力",
                key="reset_confirm_input",
                placeholder=current_user,
            )
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("リセット実行", key="reset_exec_btn"):
                    if confirm_name.strip() == current_user:
                        try:
                            _reset_answer_history_only()
                        except Exception as exc:
                            st.error(f"成績リセットに失敗しました: {exc}")
                            st.session_state["confirm_reset"] = False
                            return
                        st.session_state["confirm_reset"] = False
                        st.rerun()
                    else:
                        st.error("ユーザー名が一致しません。リセットを中止しました。")
            with rc2:
                if st.button("キャンセル", key="reset_cancel_btn"):
                    st.session_state["confirm_reset"] = False
                    st.rerun()



def _rate_bar(rate: float) -> str:
    """正解率に応じた色付きバーをHTMLで返す。"""
    if rate < 0.5:
        bar_color = "#e57373"  # 赤系
    elif rate < 0.8:
        bar_color = "#ffb74d"  # 橙系
    else:
        bar_color = "#64b5f6"  # 青系
    pct = f"{rate * 100:.0f}%"
    return (
        f"<span style='display:inline-block;width:60px;height:10px;"
        f"background:#e0e0e0;border-radius:5px;vertical-align:middle;'>"
        f"<span style='display:inline-block;width:{pct};height:10px;"
        f"background:{bar_color};border-radius:5px;'></span></span>"
        f"&nbsp;<small>{rate*100:.1f}%</small>"
    )


_CAT1_ORDER = ["基本演習", "標準演習", "応用演習"]


def _sorted_cat1(keys: list[str]) -> list[str]:
    return sorted(keys, key=lambda c: (_CAT1_ORDER.index(c) if c in _CAT1_ORDER else len(_CAT1_ORDER), c))



def _render_all_questions_tree() -> None:
    all_questions = load_questions_from_db(DB_PATH)
    user_name = st.session_state.get("user_name", "")
    stats = load_question_stats(DB_PATH, user_name)  # {question_id: (asked, correct, incorrect)}

    if not all_questions:
        st.info("問題がありません。")
        return

    # ツリー構築（questions は source_csv, number, id 順で取得済み → 挿入順 = CSV並び順）
    tree: dict[str, list[Question]] = defaultdict(list)
    for q in all_questions:
        tree[q.category].append(q)

    for cat1 in tree.keys():
        qs_cat1 = tree[cat1]
        answered_cat1 = [q for q in qs_cat1 if q.id in stats]
        asked_total = sum(stats[q.id][0] for q in answered_cat1)
        correct_total = sum(stats[q.id][1] for q in answered_cat1)
        cat1_rate_str = (
            f"　正解率: {correct_total/asked_total*100:.1f}%" if asked_total > 0 else ""
        )
        label_cat1 = (
            f"📁 {cat1}　{len(answered_cat1)}/{len(qs_cat1)}問回答済{cat1_rate_str}"
        )

        with st.expander(label_cat1, expanded=False):
            html_parts = []
            for q in qs_cat1:
                english_text = html.escape(q.english or "(No English text)")
                if q.id in stats:
                    asked, correct, incorrect = stats[q.id]
                    rate = correct / asked if asked > 0 else 0.0
                    bg_color = "#fdecec" if rate < 0.5 else ("#fff8e6" if rate < 0.8 else "#e6f4ff")
                    item_bar = _rate_bar(rate)
                    html_parts.append(
                        f"<div style='background:{bg_color};padding:0.45rem 0.7rem;"
                        "border-radius:6px;margin-bottom:0.25rem;white-space:pre-wrap;line-height:1.5;'>"
                        f"{english_text}<br>"
                        f"<small>{item_bar}&nbsp;|&nbsp;"
                        f"正解: {correct} / 不正解: {incorrect} / 計: {asked} 回</small>"
                        "</div>"
                    )
                else:
                    html_parts.append(
                        f"<div style='background:#f0f0f0;padding:0.45rem 0.7rem;"
                        "border-radius:6px;margin-bottom:0.25rem;white-space:pre-wrap;"
                        "line-height:1.5;color:#888;'>"
                        f"{english_text}<br>"
                        "<small>未出題</small>"
                        "</div>"
                    )
            st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_login() -> None:
    st.title("📘 English Quiz")

    # ── ログインフォーム ──
    authenticator.login(location="main")

    if st.session_state.get("authentication_status") is True:
        # 認証成功 → user_name をセットしてメイン画面へ
        st.session_state.user_name = st.session_state.get("username", "")
        st.session_state.stage = "setup"
        st.rerun()
    elif st.session_state.get("authentication_status") is False:
        st.error("ユーザー名またはパスワードが正しくありません。")

    # ── 新規ユーザー登録 ──
    st.divider()
    with st.expander("新規ユーザー登録"):
        with st.form("register_form"):
            new_username = st.text_input("ユーザー名（ログインID）※半角英数字", max_chars=32)
            new_nickname = st.text_input("ニックネーム（表示名）", max_chars=32)
            new_password = st.text_input("パスワード", type="password")
            new_password2 = st.text_input("パスワード（確認）", type="password")
            submitted = st.form_submit_button("Register")
        if submitted:
            import bcrypt
            # 入力バリデーション
            if not new_username or not new_nickname or not new_password:
                st.error("すべての項目を入力してください。")
            elif not new_username.isalnum():
                st.error("ユーザー名は半角英数字のみ使用できます。")
            elif new_password != new_password2:
                st.error("パスワードが一致しません。")
            elif new_username in _config["credentials"]["usernames"]:
                st.error("このユーザー名は既に登録されています。別のユーザー名を入力してください。")
            else:
                hashed_pw = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
                _config["credentials"]["usernames"][new_username] = {
                    "nickname": new_nickname,
                    "password": hashed_pw
                }
                _save_config()
                st.success(f"ユーザー「{new_nickname}」を登録しました。上のフォームからログインしてください。")


def render_history() -> None:
    st.title("成績リスト")
    _render_all_questions_tree()

    if st.button("メイン画面に戻る", type="primary"):
        st.session_state.stage = "setup"
        st.rerun()


def render_quiz() -> None:
    questions = st.session_state.quiz_questions
    index = st.session_state.current_index

    if index >= len(questions):
        st.session_state.stage = "result"
        st.rerun()

    q = questions[index]

    record_error = st.session_state.pop("record_error", "")
    if record_error:
        st.warning(record_error)

    st.title("English Quiz")

    prog_col, abort_col = st.columns([5, 1])
    with prog_col:
        st.progress((index + 1) / len(questions), text=f"{index + 1} / {len(questions)}")
    with abort_col:
        if st.button("中断する", key="abort_quiz"):
            st.session_state.stage = "result"
            st.rerun()

    st.subheader(f"Q{index + 1}")
    question_text = q.english or "(No English text)"
    st.markdown(
        (
            "<div style='white-space: pre-wrap;line-height:1.6;'>"
            f"{html.escape(question_text)}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.write("")  # 問題文と選択肢の間の空行

    # 選択肢のシャッフル順を生成・保持（問題ごとに固定）
    shuffle_key = f"shuffle_order_{index}"
    if shuffle_key not in st.session_state:
        order = list(range(4))  # [0, 1, 2, 3]
        random.shuffle(order)
        st.session_state[shuffle_key] = order
    shuffle_order: list[int] = st.session_state[shuffle_key]
    choices = [q.choice1, q.choice2, q.choice3, q.choice4]

    for display_pos, original_idx in enumerate(shuffle_order):
        choice = choices[original_idx]
        original_choice_index = original_idx + 1  # 1-based（正解判定用）
        label = f"{display_pos + 1}. {choice}"
        st.button(
            label,
            key=f"choice_{index}_{display_pos}",
            disabled=st.session_state.answered,
            on_click=_answer_question,
            args=(original_choice_index,),
        )

    if st.session_state.answered:
        selected = st.session_state.selected_index
        correcting_key = f"correcting_{index}"
        corrected_key = f"corrected_{index}"
        if correcting_key not in st.session_state:
            st.session_state[correcting_key] = False
        if corrected_key not in st.session_state:
            st.session_state[corrected_key] = False

        if st.session_state[corrected_key]:
            # 修正済み → メッセージと「次の問題へ」のみ表示
            st.success("正解を修正しました。")
            if st.button("次の問題へ", type="primary"):
                st.session_state.current_index += 1
                st.session_state.answered = False
                st.session_state.selected_index = None
                st.rerun()
        elif st.session_state[correcting_key]:
            # 修正中 → 選択肢を表示
            if is_correct(q, selected):
                st.success("正解です！")
            else:
                correct_original_idx = q.answer - 1
                correct_display_pos = shuffle_order.index(correct_original_idx) + 1
                st.error(f"不正解です。正解は {correct_display_pos}. {choices[correct_original_idx]}")
            st.info("正解を選んでください")
            fix_cols = st.columns(4)
            symbols = ["①", "②", "③", "④"]
            for ci in range(4):
                with fix_cols[ci]:
                    if st.button(
                        f"{symbols[ci]} {choices[ci]}",
                        key=f"fix_choice_{index}_{ci+1}",
                    ):
                        new_correct = ci + 1
                        try:
                            update_correct_index(DB_PATH, q.id, new_correct)
                            updated_q = Question(
                                id=q.id,
                                source_csv=q.source_csv,
                                category=q.category,
                                english=q.english,
                                choice1=q.choice1,
                                choice2=q.choice2,
                                choice3=q.choice3,
                                choice4=q.choice4,
                                answer=new_correct,
                                japanese=q.japanese,
                                row_index=q.row_index,
                            )
                            st.session_state.quiz_questions[index] = updated_q
                            if index < len(st.session_state.answer_history):
                                was_correct = (selected == new_correct)
                                st.session_state.answer_history[index]["is_correct"] = was_correct
                                st.session_state.answer_history[index]["correct_index"] = new_correct
                                st.session_state.answer_history[index]["correct_text"] = choices[new_correct - 1]
                                st.session_state.correct_count = sum(
                                    1 for h in st.session_state.answer_history if h.get("is_correct")
                                )
                        except Exception as exc:
                            st.error(f"正解の修正に失敗しました: {exc}")
                        st.session_state[correcting_key] = False
                        st.session_state[corrected_key] = True
                        st.rerun()
        else:
            # 通常の回答後表示
            if is_correct(q, selected):
                st.success("正解です！")
            else:
                correct_original_idx = q.answer - 1
                correct_display_pos = shuffle_order.index(correct_original_idx) + 1
                st.error(f"不正解です。正解は {correct_display_pos}. {choices[correct_original_idx]}")

            if st.button("次の問題へ", type="primary"):
                st.session_state.current_index += 1
                st.session_state.answered = False
                st.session_state.selected_index = None
                st.rerun()

            # 正解を修正するボタン（一番下・Georgeのみ）
            if st.session_state.get("user_name", "") == "George":
                if st.button("正解を修正する", key=f"fix_btn_{index}"):
                    st.session_state[correcting_key] = True
                    st.rerun()

    if st.session_state.show_japanese and q.prompt:
        st.caption(f"日本語: {q.prompt}")


def render_result() -> None:
    answer_history = st.session_state.get("answer_history", [])
    answered_count = len(answer_history)
    total = len(st.session_state.quiz_questions)
    correct = st.session_state.correct_count

    st.title("結果")

    if answered_count < total:
        st.warning(f"{total} 問中 {answered_count} 問で中断しました。")

    st.metric("正答数", f"{correct} / {answered_count}")

    if answered_count > 0:
        score = (correct / answered_count) * 100
        st.write(f"正答率: {score:.1f}%")

    st.subheader("回答サマリー")
    for idx in range(answered_count):
        question = st.session_state.quiz_questions[idx]
        english_text = html.escape(question.english or "(No English text)")
        history = answer_history[idx]
        is_ok = bool(history.get("is_correct"))
        status = "OK" if is_ok else "NG"
        bg_color = "#e6f4ff" if is_ok else "#fdecec"
        correct_text = html.escape(history.get("correct_text", ""))
        st.markdown(
            (
                f"<div style='background:{bg_color};padding:0.55rem 0.7rem;"
                "border-radius:8px;margin-bottom:0.35rem;white-space: pre-wrap;'>"
                f"{idx + 1}. [{status}] {english_text}　<b>答: {correct_text}</b>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    if st.button("もう一度", type="primary"):
        restart()
        st.rerun()


init_state()

try:
    all_questions = load_questions()
except Exception as exc:
    st.error(f"問題データの読み込みに失敗しました: {exc}")
    st.stop()

# cookie で認証済みならログインステージをスキップ
if (
    st.session_state.get("authentication_status") is True
    and st.session_state.stage == "login"
):
    st.session_state.user_name = st.session_state.get("username", "")
    st.session_state.stage = "setup"

if st.session_state.stage == "login":
    render_login()
elif st.session_state.stage == "setup":
    render_setup(all_questions)
elif st.session_state.stage == "quiz":
    render_quiz()
elif st.session_state.stage == "history":
    render_history()
else:
    render_result()

