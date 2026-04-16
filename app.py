from __future__ import annotations

from collections import defaultdict
import html
from pathlib import Path
import random
import re

import streamlit as st

from quiz_logic import (
    Question,
    export_correct_answers_to_csvs,
    filter_questions,
    get_category_options,
    is_correct,
    limit_questions,
    load_default_tags,
    load_questions_from_db,
    reload_db_from_csvs,
    sync_csvs_to_db,
    update_correct_index,
)
from local_storage_helper import (
    init_local_storage,
    ensure_loaded,
    save_app_data,
    get_registered_users,
    register_user,
    user_exists,
    get_last_user,
    set_last_user,
    get_question_stats,
    record_answer,
    reset_user_stats,
    delete_user,
    get_all_tags,
    set_all_tags,
    get_question_tags,
    set_question_tags,
)
from db_initializer import initialize_db_from_initial_csv

INPUT_DIR = Path(__file__).parent / "input"
DB_PATH = Path(__file__).parent / "quiz.db"

st.set_page_config(page_title="English Quiz", page_icon="📘", layout="centered")

# ── ブラウザ localStorage の初期化 ──────────────────────────
ls = init_local_storage()
ensure_loaded(ls)


def _apply_default_tags() -> None:
    """DBのdefault_tagsをlocalStorageのタグ情報にマージする（未設定の問題のみ）。"""
    db_defaults = load_default_tags(DB_PATH)
    if not db_defaults:
        return
    all_tags = get_all_tags()
    question_tags = get_question_tags()
    changed = False
    for qid, tag in db_defaults.items():
        qid_str = str(qid)
        # 既にタグが付いている問題はスキップ
        if qid_str in question_tags and question_tags[qid_str]:
            continue
        # タグ一覧に無ければ追加
        if tag not in all_tags:
            all_tags.append(tag)
            changed = True
        question_tags[qid_str] = [tag]
        changed = True
    if changed:
        set_all_tags(all_tags)
        set_question_tags(question_tags)


# 初回ロード時にデフォルトタグを適用
if "_default_tags_applied" not in st.session_state:
    _apply_default_tags()
    st.session_state["_default_tags_applied"] = True


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
        record_answer(current_question.id, answer_is_correct, st.session_state.get("user_name", ""))
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
    questions: list[Question], count: int, user_name: str = ""
) -> tuple[list[Question], str]:
    """おすすめモード用の出題プールを作成する。

    - 未出題問題がある → その中からシャッフルして count 問選ぶ
    - 全問出題済み → 正解率が低い順に count 問選んでシャッフル
    戻り値: (シャッフル済み選択問題リスト, 説明メッセージ)
    """
    stats = get_question_stats(user_name)  # {question_id: (asked, correct, incorrect)}
    unanswered = [q for q in questions if q.id not in stats]

    if unanswered:
        if len(unanswered) >= count:
            selected = random.sample(unanswered, count)
            desc = f"未出題 {len(unanswered)} 問からシャッフルで {len(selected)} 問出題"
        else:
            # 未出題が足りない場合は、残りを正解率が低い順に出題済みから補う
            needed = count - len(unanswered)
            def _rate(q: Question) -> float:
                asked, correct, _ = stats.get(q.id, (1, 0, 0))
                return correct / asked if asked > 0 else 0.0
            # 出題済みの中から正解率が低い順に不足分を選ぶ
            already_asked = [q for q in questions if q.id in stats]
            already_asked_sorted = sorted(already_asked, key=_rate)
            supplement = already_asked_sorted[:needed]
            # 未出題はシャッフル、補充分はそのまま
            selected = random.sample(unanswered, len(unanswered)) + supplement
            desc = f"未出題{len(unanswered)}問＋正解率低い{len(supplement)}問を出題"
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
    # デフォルトタグを再適用（既存タグをクリアして再設定）
    set_question_tags({})
    set_all_tags([])
    _apply_default_tags()
    st.session_state["_default_tags_applied"] = True
    restart()
    st.session_state.reload_notice = (
        f"DBをクリアして再読込しました（取込CSV: {imported_count}件 / 問題数: {len(reloaded_questions)}件）"
    )


def _reset_answer_history_only() -> None:
    user_name = st.session_state.get("user_name", "")
    reset_user_stats(user_name)
    st.session_state.reload_notice = f"「{user_name}」の学習成績をリセットしました。"


def render_setup(all_questions: list[Question]) -> None:
    st.title("English Quiz")
    user_name = st.session_state.get("user_name", "")

    header_col, logout_col = st.columns([5, 1])
    with header_col:
        if user_name:
            st.caption(f"👤 {user_name}")
    with logout_col:
        if st.button("切替", key="switch_user"):
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

    # ── タグで出題範囲を絞り込み ──
    all_tags = get_all_tags()
    question_tags = get_question_tags()
    tag_filter_options = ["すべて"] + [f"#{t}" for t in all_tags] + ["未タグのみ"]
    selected_tag_filter = st.radio(
        "タグで絞り込み",
        options=tag_filter_options,
        horizontal=True,
        key="setup_tag_filter",
    )

    if selected_tag_filter == "すべて":
        target_questions = all_questions
    elif selected_tag_filter == "未タグのみ":
        tagged_ids = {qid for qid, tags in question_tags.items() if tags}
        target_questions = [q for q in all_questions if str(q.id) not in tagged_ids]
    else:
        filter_tag = selected_tag_filter[1:]  # remove #
        target_questions = [
            q for q in all_questions
            if filter_tag in question_tags.get(str(q.id), [])
        ]

    count_mode = st.radio(
        "出題数",
        options=["10問", "20問", "30問", "50問", "全部"],
        horizontal=True,
    )
    preset_map = {"10問": 10, "20問": 20, "30問": 30, "50問": 50}
    question_count = preset_map.get(count_mode, len(target_questions))

    if order_mode == "おすすめ":
        user_name = st.session_state.get("user_name", "")
        quiz_questions, recommend_desc = _build_recommended_pool(target_questions, question_count, user_name)
        st.info(f"🌟 おすすめ：{recommend_desc}（対象問題数: {len(target_questions)}）")
    else:
        if order_mode == "シャッフル":
            pool = random.sample(target_questions, len(target_questions))
            quiz_questions = limit_questions(pool, question_count)
            st.info(f"対象問題数: {len(target_questions)} / 出題数: {len(quiz_questions)}")
        elif order_mode == "順番通り（出題少ない順）":
            # 出題回数が少ない順にソート（同回数なら元の並び順を維持）
            user_name = st.session_state.get("user_name", "")
            stats = get_question_stats(user_name)
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

    if st.button("🏷️ タグ管理"):
        st.session_state.stage = "tag_manage"
        st.rerun()

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

    # ...existing code...


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
    stats = get_question_stats(user_name)  # {question_id: (asked, correct, incorrect)}
    question_tags = get_question_tags()
    all_tags = get_all_tags()

    if not all_questions:
        st.info("問題がありません。")
        return

    # タグごとにグルーピング（複数タグがある問題は各タグに重複表示）
    tag_groups: dict[str, list[Question]] = {}
    for tag in all_tags:
        tag_groups[tag] = []
    tag_groups["未タグ"] = []

    for q in all_questions:
        qid = str(q.id)
        q_tags = question_tags.get(qid, [])
        if not q_tags:
            tag_groups["未タグ"].append(q)
        else:
            for tag in q_tags:
                if tag in tag_groups:
                    tag_groups[tag].append(q)

    # 表示順: 定義済みタグ → 未タグ
    display_order = all_tags + ["未タグ"]

    for group_name in display_order:
        qs = tag_groups.get(group_name, [])
        if not qs:
            continue

        answered_qs = [q for q in qs if q.id in stats]
        asked_total = sum(stats[q.id][0] for q in answered_qs)
        correct_total = sum(stats[q.id][1] for q in answered_qs)
        rate_str = (
            f"　正解率: {correct_total/asked_total*100:.1f}%" if asked_total > 0 else ""
        )
        label = f"🏷️ #{group_name}　{len(answered_qs)}/{len(qs)}問回答済{rate_str}"

        with st.expander(label, expanded=False):
            html_parts = []
            for q in qs:
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

    # ── 既存ユーザー選択 ──
    users = get_registered_users()
    last_user = get_last_user()

    if users:
        st.subheader("ユーザーを選択")
        user_names = [u["user_name"] for u in users]

        # 前回のユーザーをデフォルトに
        default_idx = 0
        if last_user in user_names:
            default_idx = user_names.index(last_user)

        selected_user = st.selectbox(
            "ユーザー",
            options=user_names,
            index=default_idx,
        )

        col_login, col_delete = st.columns([2, 1])
        with col_login:
            if st.button("ログイン", type="primary"):
                st.session_state.user_name = selected_user
                set_last_user(selected_user)
                st.session_state.stage = "setup"
                st.rerun()
        with col_delete:
            if st.button("ユーザー削除", key="delete_user_btn"):
                delete_user(selected_user)
                st.success(f"ユーザー「{selected_user}」を削除しました。")
                st.rerun()
    else:
        st.info("ユーザーが登録されていません。下の「新規ユーザー登録」から登録してください。")

    # ── 新規ユーザー登録 ──
    st.divider()
    with st.expander("新規ユーザー登録"):
        with st.form("register_form"):
            new_username = st.text_input("ユーザー名", max_chars=32)
            submitted = st.form_submit_button("登録")
        if submitted:
            if not new_username or not new_username.strip():
                st.error("ユーザー名を入力してください。")
            elif user_exists(new_username.strip()):
                st.error("このユーザー名は既に登録されています。別のユーザー名を入力してください。")
            else:
                register_user(new_username.strip())
                st.success(f"ユーザー「{new_username.strip()}」を登録しました。上のリストからログインしてください。")
                st.rerun()


def render_history() -> None:
    st.title("成績リスト")
    _render_all_questions_tree()

    if st.button("メイン画面に戻る", type="primary"):
        st.session_state.stage = "setup"
        st.rerun()


def render_tag_manage() -> None:
    """タグ管理画面：どの問題にどのハッシュタグが付いているかを一覧・編集できる。"""
    st.title("🏷️ タグ管理")

    all_questions = load_questions_from_db(DB_PATH)
    question_tags = get_question_tags()
    all_tags = get_all_tags()

    if st.button("メイン画面に戻る", type="primary", key="tag_manage_back"):
        st.session_state.stage = "setup"
        st.rerun()

    # ── タグ一覧と新規タグ作成 ──
    st.subheader("タグ一覧")
    if all_tags:
        st.write("　".join([f"`#{t}`" for t in all_tags]))
    else:
        st.caption("タグはまだありません。下のフォームから作成してください。")

    with st.form("tag_manage_add_form", clear_on_submit=True):
        new_tag = st.text_input("新しいタグを作成", placeholder="タグ名を入力")
        if st.form_submit_button("タグを作成"):
            if new_tag.strip():
                tag = new_tag.strip()
                if tag not in all_tags:
                    all_tags.append(tag)
                    set_all_tags(all_tags)
                    st.rerun()
                else:
                    st.warning(f"タグ「#{tag}」は既に存在します。")

    # ── タグ削除 ──
    if all_tags:
        with st.expander("タグを削除する"):
            del_tag = st.selectbox("削除するタグ", options=all_tags, key="del_tag_select")
            if st.button("このタグを削除", key="del_tag_btn"):
                all_tags = [t for t in all_tags if t != del_tag]
                set_all_tags(all_tags)
                for qid in list(question_tags.keys()):
                    question_tags[qid] = [t for t in question_tags[qid] if t != del_tag]
                    if not question_tags[qid]:
                        del question_tags[qid]
                set_question_tags(question_tags)
                st.rerun()

    st.divider()

    # ── Excel風テーブル（st.data_editor） ──
    st.subheader("問題一覧")

    if not all_questions:
        st.caption("問題がありません。")
    elif not all_tags:
        st.caption("タグを作成すると、ここに問題×タグの表が表示されます。")
    else:
        import pandas as pd

        # DataFrame構築: 問題ID(hidden), 問題文, 各タグ(bool)
        rows = []
        for q in all_questions:
            qid = str(q.id)
            q_tags = question_tags.get(qid, [])
            row: dict = {
                "_qid": qid,
                "問題文": (q.english or "(No English text)")[:100],
            }
            for tag in all_tags:
                row[f"#{tag}"] = tag in q_tags
            rows.append(row)

        df = pd.DataFrame(rows)

        edited_df = st.data_editor(
            df,
            column_config={
                "_qid": None,  # 非表示
                "問題文": st.column_config.TextColumn("問題文", disabled=True, width="large"),
                **{
                    f"#{tag}": st.column_config.CheckboxColumn(f"#{tag}", default=False)
                    for tag in all_tags
                },
            },
            hide_index=True,
            use_container_width=True,
            key="tag_data_editor",
        )

        # 変更を検出して保存
        changed = False
        for _, erow in edited_df.iterrows():
            qid = str(erow["_qid"])
            new_tags = [tag for tag in all_tags if erow.get(f"#{tag}", False)]
            old_tags = question_tags.get(qid, [])
            if sorted(new_tags) != sorted(old_tags):
                if new_tags:
                    question_tags[qid] = new_tags
                elif qid in question_tags:
                    del question_tags[qid]
                changed = True
        if changed:
            set_question_tags(question_tags)
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

    if st.session_state.show_japanese and q.japanese:
        st.caption(f"日本語: {q.japanese}")

    # --- タグ管理UI（画面一番下） ---
    question_tags = get_question_tags()
    all_tags = get_all_tags()
    qid = str(q.id)
    q_tags = question_tags.get(qid, [])

    st.markdown("---")
    st.markdown("#### タグ（ハッシュタグ）")
    if all_tags:
        tag_cols = st.columns(len(all_tags))
        for i, tag in enumerate(all_tags):
            selected = tag in q_tags
            btn_label = f"#{tag}" if not selected else f"✅ #{tag}"
            if tag_cols[i].button(btn_label, key=f"tagbtn_{q.id}_{tag}"):
                if selected:
                    new_tags = [t for t in q_tags if t != tag]
                else:
                    new_tags = q_tags + [tag]
                if new_tags != q_tags:
                    question_tags[qid] = new_tags
                    set_question_tags(question_tags)
                    st.rerun()
    else:
        st.caption("タグはまだありません")

    # 新規タグ追加
    with st.form(f"add_tag_form_{q.id}", clear_on_submit=True):
        new_tag = st.text_input("新しいタグを追加", key=f"new_tag_input_{q.id}")
        submitted = st.form_submit_button("追加")
        if submitted and new_tag.strip():
            tag = new_tag.strip()
            updated = False
            if tag not in all_tags:
                all_tags.append(tag)
                set_all_tags(all_tags)
                updated = True
            q_tags = question_tags.get(qid, [])
            if tag not in q_tags:
                q_tags.append(tag)
                question_tags[qid] = q_tags
                set_question_tags(question_tags)
                updated = True
            if updated:
                st.rerun()


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


if st.session_state.stage == "login":
    render_login()
elif st.session_state.stage == "setup":
    render_setup(all_questions)
elif st.session_state.stage == "quiz":
    render_quiz()
elif st.session_state.stage == "history":
    render_history()
elif st.session_state.stage == "tag_manage":
    render_tag_manage()
else:
    render_result()

# ── ページ描画後にブラウザ localStorage へ永続化 ──────────────
save_app_data(ls)

