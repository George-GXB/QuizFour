from __future__ import annotations
# HTMLメール生成関数（グローバル定義）は下部で型付きで定義されています。

import streamlit as st
import random
import html
import re
from pathlib import Path
from quiz_logic import Question, sync_csvs_to_db, load_questions_from_db, reload_db_from_csvs, limit_questions, is_correct
from local_storage_helper import (
    init_local_storage, ensure_loaded, record_answer, get_question_stats, get_daily_stats, add_daily_study_seconds, record_quiz_session, get_fastest_time_for_count, reset_user_stats, set_default_tags, set_default_question_tags,
    get_all_tags, get_question_tags, get_default_tags, get_default_question_tags, get_system_tags, get_system_question_tags,
    set_question_tags, set_system_question_tags, set_all_tags, save_app_data, get_registered_users, get_last_user, set_last_user, user_exists, register_user, delete_user, get_share_emails, set_share_emails,
    get_user_settings, set_user_settings
)


DB_PATH = Path(__file__).parent / "quiz.db"
INPUT_DIR = Path(__file__).parent / "input"

# 出題モードの選択肢を定義（一定にしておくと UI の消失/重複を防止できます）
ORDER_MODE_OPTIONS = ["おすすめ", "シャッフル", "順番通り", "順番通り（出題少ない順）"]


def _effective_order_mode() -> str:
    """セッション/保存値から実際に使う出題モードを決定して返す。

    優先順位:
      1. ウィジェットが管理する session_state['order_mode'] が有効ならそれを使う
      2. セッション内の user_saved_order_mode (永続値のコピー) が有効ならそれを使う
      3. session_state の order_mode があればそれを使う
      4. 最終手段でデフォルト "おすすめ"
    この関数を使うことで LocalStorage とウィジェットの競合による一時的な切替を防ぐ。
    """
    try:
        om = st.session_state.get('order_mode', None)
        if om in ORDER_MODE_OPTIONS:
            return om
    except Exception:
        pass
    try:
        saved = st.session_state.get('user_saved_order_mode', None)
        if saved in ORDER_MODE_OPTIONS:
            return saved
    except Exception:
        pass
    try:
        fallback = st.session_state.get('order_mode', None)
        if fallback in ORDER_MODE_OPTIONS:
            return fallback
    except Exception:
        pass
    return "おすすめ"


# Initialize LocalStorage component and ensure app data loaded into session
LS = init_local_storage()
ensure_loaded(LS)


def _is_dark_mode() -> bool:
    """Streamlit のテーマ設定が dark のとき True。"""
    # セッションで強制テーマが設定されていればそれを優先する。
    forced = st.session_state.get("forced_theme", None)
    if forced == "dark":
        return True
    if forced == "light":
        return False
    # デフォルトは設定オプションに従う
    try:
        return st.get_option("theme.base") == "dark"
    except Exception:
        return False


def _theme_color(light: str, dark: str) -> str:
    """ライト/ダークで使う色を切り替える。"""
    return dark if _is_dark_mode() else light


def _theme_text_color(light: str = "#111111", dark: str = "#f3f4f6") -> str:
    return dark if _is_dark_mode() else light


def _theme_muted_text_color() -> str:
    return "#9ca3af" if _is_dark_mode() else "#666666"


def _theme_border_color() -> str:
    return "#374151" if _is_dark_mode() else "#dddddd"


def _load_explanation_for_question(q: Question) -> str | None:
    """Try to load explanation text for the given question.

    Tries several filename patterns under the detailed_explanations/ directory:
    - Q_{n:05d}.txt
    - Q__{n:05d}.txt
    where n is tried as (row_index+1) and then question id.
    Returns the file content as a string or None if not found.
    """
    try:
        base_dir = Path(__file__).parent / "detailed_explanations"
        if not base_dir.exists():
            return None
        candidates = []
        try:
            # try row_index-based numbering (CSV row number assumed 0-based)
            n1 = int(q.row_index) + 1 if hasattr(q, "row_index") else None
            if n1:
                candidates.append(f"Q_{n1:05d}.txt")
                candidates.append(f"Q__{n1:05d}.txt")
        except Exception:
            pass
        try:
            # try question id
            nid = int(q.id)
            candidates.append(f"Q_{nid:05d}.txt")
            candidates.append(f"Q__{nid:05d}.txt")
        except Exception:
            pass

        # Also consider files starting with Q_ and containing the id anywhere
        for fname in candidates:
            p = base_dir / fname
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8")
                except Exception:
                    try:
                        return p.read_text(encoding="cp932")
                    except Exception:
                        return p.read_text(errors="ignore")
        return None
    except Exception:
        return None
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
        "voice_mode": False,
        "voice_repeat": 2,
        "order_mode": "おすすめ", # Add default order_mode here
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


def render_theme_toggle() -> None:
    """テーマ選択の UI を廃止しました。
    デフォルトテーマは Streamlit の設定（.streamlit/config.toml の theme.base）で指定してください。
    この関数は起動時にセッションの forced_theme を初期化するだけで、ボタン等は表示しません。
    """
    # セッションの forced_theme を初期化
    if "forced_theme" not in st.session_state:
        try:
            base = st.get_option("theme.base")
            st.session_state["forced_theme"] = base if base in ("light", "dark") else "light"
        except Exception:
            # 環境によっては取得できない場合があるため安全にフォールバック
            st.session_state["forced_theme"] = "light"

    # forced_theme の値に基づきクライアント側でダークテーマを強制する CSS/JS を注入する。
    # Streamlit の内部テーマ設定を変更するのではなく、表示系の色（背景/文字色/ボタン等）を
    # 上書きすることで「適用」時に画面全体をダーク配色に揃えます。
    forced = st.session_state.get("forced_theme", None)
    try:
        # 適用対象は forced が 'dark' のとき。light のときは attribute を明示的に 'light' にする。
        theme_attr = forced if forced in ("light", "dark") else "light"

        # Streamlit の components.html は iframe を作るため、そこに挿入したスクリプト/CSS は
        # 親ドキュメントに影響を与えません。画面全体の色を確実に切り替えるためには
        # 親ドキュメントに直接スタイルを注入する必要があるため、st.markdown を優先して使います。
        try:
            if forced == 'dark':
                css_force_dark = """
<style>
/* 全体の背景と基本文字色 */
html, body, .stApp, .main, .block-container, .stContainer {
  background-color: #0b1220 !important;
  color: #e5e7eb !important;
}
/* 見出し・テキスト類を明示的に上書き（ログイン画面のタイトル等） */
.stTitle, .stHeader, .stMarkdown, .stText, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown p, h1, h2, h3, h4, .block-container h1, .block-container h2 {
  color: #e5e7eb !important;
}
/* ボタンや入力、サイドバー等の色も上書き */
.stButton>button, button, .stButton>div>button {
  background-color: #1f2937 !important;
  color: #e5e7eb !important;
  border-color: #374151 !important;
}
.stTextInput>div, .stTextInput>div>input, .stTextInput>div>textarea, input[type="text"], input[type="search"], .stSelectbox>div, .stTextArea>div>textarea {
  background-color: #000000 !important;
  color: #e5e7eb !important; /* 白系 */
  -webkit-text-fill-color: #e5e7eb !important; /* Chromium系ブラウザ用 */
  caret-color: #e5e7eb !important;
  border-color: #374151 !important;
  background-image: none !important;
  box-shadow: none !important;
}
/* 強制的に背景を黒にするため、Streamlitの入れ子構造や自動生成クラスも幅広く対象にする */
.stTextInput, .stTextInput > div, .stTextInput > div > div, .stTextInput > div > div > input, .stTextInput > div > div > textarea,
input[class*="css-"], textarea[class*="css-"] {
  background-color: #000000 !important;
  background-image: none !important;
  box-shadow: none !important;
  color: #e5e7eb !important;
  -webkit-text-fill-color: #e5e7eb !important;
}
/* プレースホルダや未入力時の色を調整（見やすくする） */
input::placeholder, textarea::placeholder, .stTextInput input::placeholder, .stTextInput textarea::placeholder {
  color: #9ca3af !important;
  opacity: 1 !important;
}
.stSidebar, .css-1lcbmhc { /* Streamlitのサイドバークラス名はバージョンにより変わるため汎用的に */
  background-color: #07101a !important;
  color: #e5e7eb !important;
}
/* テーブルや細かいテキスト */
table, th, td, .stCaption, .stMetric {
  color: #e5e7eb !important;
  border-color: #374151 !important;
}
/* リンク色 */
a { color: #93c5fd !important; }
/* ラベル・ラジオ・セレクト等の項目テキストが見えない問題を防ぐため広範囲に適用 */
.stApp * {
  color: #e5e7eb !important;
}
.stApp label, .stApp .stRadio, .stApp .stRadio label, .stApp .stSelectbox, .stApp .stCheckboxLabel {
  color: #e5e7eb !important;
}
/* Streamlit の Selectbox 内部コンテナの背景を確実に黒にする（バージョン依存のクラス名 st-c8 をターゲット） */
.stSelectbox .st-c8 { background-color: #000 !important; }
</style>
"""
                st.markdown(css_force_dark, unsafe_allow_html=True)
                # Chromium系ブラウザで Streamlit が内部的に背景画像や影を付ける場合があるため
                # JavaScript で描画後に強制的に入力要素のスタイルを上書きするスクリプトを注入する。
                js_force = """
<script>
(function(){
  try{
    function applyInputs(){
      var els = document.querySelectorAll('.stApp input, .stApp textarea, .stApp .stTextInput input, .stApp .stTextInput textarea, .stApp [role="combobox"], .stApp input[aria-label*="ユーザー"], .stApp div[class*="st-cx"]');
      els.forEach(function(el){
        try{
                          el.style.backgroundColor = '#000000';
                          el.style.color = '#e5e7eb';
          el.style.boxShadow = 'none';
          el.style.backgroundImage = 'none';
          el.style.webkitTextFillColor = '#e5e7eb';
          el.style.caretColor = '#e5e7eb';
        }catch(e){}
        // 親コンテナも黒背景にして見た目の白フレームを潰す
        try{
          var p = el.closest('div');
          if(p){ p.style.backgroundColor = '#000000'; p.style.backgroundImage = 'none'; p.style.boxShadow = 'none'; }
        }catch(e){}
      });
      // セレクト風コンテナやラベルの色も調整
      var labels = document.querySelectorAll('.stApp .stSelectbox, .stApp .st-cx, .stApp .st-c1, .stApp .st-cv');
      labels.forEach(function(lb){ try{ lb.style.color = '#e5e7eb'; lb.style.backgroundColor = 'transparent'; }catch(e){} });
    }
    applyInputs();
    var obs = new MutationObserver(function(){ applyInputs(); });
    obs.observe(document.body, {childList:true, subtree:true});
  }catch(e){}
})();
</script>
"""
                try:
                    st.markdown(js_force, unsafe_allow_html=True)
                except Exception:
                    pass
            else:
                # light のときは上書きスタイルをリセットするスタイルを注入
                css_reset = """
<style>
html, body, .stApp, .main, .block-container, .stContainer { background-color: initial !important; color: initial !important; }
input, textarea, .stTextInput>div>input, .stTextInput>div>textarea, .stSelectbox>div, .stTextArea>div>textarea { background-color: initial !important; color: initial !important; border-color: initial !important; }
.stSidebar { background-color: initial !important; color: initial !important; }
table, th, td { border-color: initial !important; }
</style>
"""
                st.markdown(css_reset, unsafe_allow_html=True)
        except Exception:
            # 安全性: 何か問題があっても UI を壊さない
            pass
    except Exception:
        # 安全第一：例外が発生しても UI を壊さない
        pass
    return

def start_quiz(questions: list[Question], show_japanese: bool) -> None:
    import time as _t
    st.session_state.stage = "quiz"
    st.session_state.quiz_questions = questions
    st.session_state.current_index = 0
    st.session_state.correct_count = 0
    st.session_state.answered = False
    st.session_state.selected_index = None
    st.session_state.show_japanese = show_japanese
    st.session_state.answer_history = []
    st.session_state.quiz_start_time = _t.time()
    # 音声モードの最初の4問はカウントダウンを動作させない
    # タイムアウト関連機能は廃止されたため、ここではタイマーを使いません。


def _toggle_selection(state_key: str, value: str) -> None:
    current_values = list(st.session_state.get(state_key, []))
    if value in current_values:
        current_values = [item for item in current_values if item != value]
    else:
        current_values.append(value)
    st.session_state[state_key] = current_values
def _render_back_to_login_button() -> None:
    """全ログイン後画面の一番下に表示する「ログイン画面に戻る」ボタン。"""
    st.divider()
    if st.button("🔙 ログイン画面に戻る", key=f"back_to_login_{st.session_state.get('stage','')}", use_container_width=True):
        st.session_state.stage = "login"
        st.rerun()


# --- 結果画面の実装 ---
def render_result() -> None:
    """クイズ終了後の結果表示画面。

    セッションの answer_history / correct_count / quiz_start_time / quiz_end_time
    などを参照してサマリおよび各問題の結果を表示します。
    """
    import time as _time

    st.title("📊 結果")
    # テーマ切替ボタン（自動 / ライト / ダーク）
    render_theme_toggle()

    questions = st.session_state.get("quiz_questions", [])
    total = len(questions)
    correct = st.session_state.get("correct_count", 0)

    # 時間情報
    start = st.session_state.get("quiz_start_time")
    end = st.session_state.get("quiz_end_time", _time.time())
    if start:
        elapsed = max(0, int(end - start))
    else:
        elapsed = None

    if total == 0:
        st.info("結果を表示するデータがありません。メイン画面に戻ります。")
        if st.button("メイン画面へ戻る"):
            st.session_state.stage = "setup"
            st.rerun()
        return

    pct = (correct / total) * 100 if total > 0 else 0.0
    c1, c2 = st.columns([2, 1])
    with c1:
        st.metric("正解数", f"{correct} / {total}", f"{pct:.1f}%")
    with c2:
        if elapsed is not None:
            st.metric("所要時間", f"{elapsed} 秒")

    # 日別グラフ表示は一時的に無効化（表示用メッセージを削除）

    st.markdown("---")

    # 各問題の詳細リスト
    history = st.session_state.get("answer_history", [])
    if history:
        for i, item in enumerate(history, start=1):
            en = item.get("english", "(No English text)")
            is_correct_flag = bool(item.get("is_correct", False))
            selected = item.get("selected_index")
            correct_idx = item.get("correct_index")
            # 表示順情報が保存されていればそれを使って選択肢を同じ並びで表示
            shuffle_order = item.get("shuffle_order") or [0, 1, 2, 3]
            display_choices = item.get("display_choices") or []

            # 選択と正解の表示位置（display_pos: 1-based）
            correct_original_idx = (correct_idx - 1) if correct_idx is not None else None
            try:
                correct_display_pos = shuffle_order.index(correct_original_idx) + 1 if correct_original_idx is not None else None
            except ValueError:
                correct_display_pos = None
            if isinstance(selected, int) and selected >= 1:
                try:
                    selected_display_pos = shuffle_order.index(selected - 1) + 1
                except ValueError:
                    selected_display_pos = None
            else:
                selected_display_pos = None

            # 見出し: Qn と正誤
            header = f"Q{i}. {html.escape(en)}"
            if is_correct_flag:
                st.success(header)
            else:
                # タイムアウトの概念は廃止されたため、不正解は単に不正解として表示する
                st.error(header)

            # 選択肢を表示（保存された表示順で）
            if display_choices:
                lines = []
                for idx_disp, text in enumerate(display_choices, start=1):
                    safe_text = html.escape(text)
                    markers: list[str] = []
                    is_corr = correct_display_pos == idx_disp
                    is_sel = selected_display_pos == idx_disp
                    if is_corr:
                        markers.append('正解')
                    if is_sel:
                        markers.append('あなたの選択')
                    marker_color = _theme_muted_text_color()
                    # ライト/ダーク別の色設定
                    if _is_dark_mode():
                        corr_bg = "#12301f"
                        corr_text = "#e5e7eb"
                        wrong_bg = "#331800"
                        wrong_text = "#e5e7eb"
                        other_bg = "transparent"
                        other_text = "#e5e7eb"
                        border_css = f"border:1px solid {_theme_border_color()};"
                    else:
                        # ユーザー要望: ライトモードでは正解を薄い青/青文字、不正解を薄い赤/赤文字
                        corr_bg = "#e6f4ff"  # 薄い青
                        corr_text = "#0b61c3"  # 青文字
                        wrong_bg = "#fdecec"  # 薄い赤
                        wrong_text = "#b91c1c"  # 赤文字
                        other_bg = "transparent"
                        other_text = "inherit"
                        border_css = ""
                    suf = f" <small style='color:{marker_color};'>({' / '.join(markers)})</small>" if markers else ""
                    # 表示スタイル決定（正解・選択の組合せで優先度を決める）
                    if is_corr and is_sel:
                        # 選択かつ正解
                        style = f"background:{corr_bg};color:{corr_text};{border_css}padding:6px;border-radius:6px;margin-bottom:4px;"
                        lines.append(f"<div style='{style}'><b>{safe_text}</b>{suf} ✅</div>")
                    elif is_sel and not is_corr:
                        # 選択したが不正解
                        style = f"background:{wrong_bg};color:{wrong_text};{border_css}padding:6px;border-radius:6px;margin-bottom:4px;"
                        lines.append(f"<div style='{style}'><b>{safe_text}</b>{suf}</div>")
                    elif is_corr:
                        # 正解（未選択）
                        style = f"background:{corr_bg};color:{corr_text};{border_css}padding:6px;border-radius:6px;margin-bottom:4px;"
                        lines.append(f"<div style='{style}'><b>{safe_text}</b>{suf}</div>")
                    else:
                        style = f"background:{other_bg};color:{other_text};padding:6px;border-radius:6px;margin-bottom:4px;"
                        lines.append(f"<div style='{style}'>{safe_text}{suf}</div>")
                st.markdown("".join(lines), unsafe_allow_html=True)
            else:
                # 互換性のため旧来の表示
                correct_text = item.get("correct_text") or ""
                if correct_text:
                    st.caption(f"正解: {correct_text}")
    else:
        st.info("詳細な履歴がありません。")

    st.markdown("---")
    col_back, col_hist, col_retry = st.columns([1, 1, 1])
    with col_back:
        if st.button("メイン画面へ戻る", type="primary"):
            st.session_state.stage = "setup"
            st.rerun()
    with col_hist:
        if st.button("成績リストを表示"):
            st.session_state.stage = "history"
            st.rerun()
    with col_retry:
        if st.button("もう一度同じ出題で再挑戦"):
            # same question set を再度 start
            try:
                start_quiz(st.session_state.get("quiz_questions", []), st.session_state.get("show_japanese", False))
            except Exception:
                st.error("再挑戦の準備に失敗しました。")
            st.rerun()

    # 画面描画後にローカルストレージへ保存
    try:
        save_app_data(LS)
    except Exception:
        pass

    _render_back_to_login_button()


def _clear_selection(state_key: str) -> None:
    st.session_state[state_key] = []


# Timeout behavior removed: client/server timeout handling has been deprecated.
# Previously there was a _timeout_question() helper here to mark unanswered
# questions as timed out; that behavior and related session keys have been removed.



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
    # Determine correctness robustly: prefer index-based check, but fall back to
    # comparing choice text (handles cases where index mapping got out-of-sync).
    choices = [current_question.choice1, current_question.choice2, current_question.choice3, current_question.choice4]
    try:
        idx = int(choice_index) - 1
    except Exception:
        idx = None
    selected_text = choices[idx] if idx is not None and 0 <= idx < len(choices) else None
    try:
        correct_idx = int(current_question.answer) - 1
    except Exception:
        correct_idx = None
    correct_text = choices[correct_idx] if correct_idx is not None and 0 <= correct_idx < len(choices) else None

    answer_is_correct = False
    try:
        # primary: index compare
        if is_correct(current_question, choice_index):
            answer_is_correct = True
        # fallback: text compare if index-based failed or ambiguous
        elif selected_text is not None and correct_text is not None and selected_text == correct_text:
            answer_is_correct = True
    except Exception:
        # safe fallback to text comparison
        if selected_text is not None and correct_text is not None and selected_text == correct_text:
            answer_is_correct = True

    if answer_is_correct:
        st.session_state.correct_count += 1

    try:
        record_answer(current_question.id, answer_is_correct, st.session_state.get("user_name", ""))
        _update_system_tags_on_answer(current_question.id, answer_is_correct)
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
            "shuffle_order": st.session_state.get(f"shuffle_order_{index}", [0, 1, 2, 3]),
            "display_choices": [f"{i+1}. {choices[o]}" for i, o in enumerate(st.session_state.get(f"shuffle_order_{index}", [0, 1, 2, 3]))],
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
            # 未出題が足りない場合は、残りを正解率の低い順に出題済みから補う
            needed = count - len(unanswered)
            def _sort_key(q: Question) -> tuple[float, int]:
                asked, correct, *_ = stats.get(q.id, (1, 0, 0, 0))
                rate = correct / asked if asked > 0 else 0.0
                return (rate, -asked)  # 正解率昇順、同率なら出題回数多い順
            # 出題済みの中から正解率が低い順（同率なら出題回数多い順）に不足分を選ぶ
            already_asked = [q for q in questions if q.id in stats]
            already_asked_sorted = sorted(already_asked, key=_sort_key)
            supplement = already_asked_sorted[:needed]
            # 未出題はシャッフル、補充分はそのまま
            selected = random.sample(unanswered, len(unanswered)) + supplement
            desc = f"未出題{len(unanswered)}問＋正解率低い{len(supplement)}問を出題"
    else:
        def _sort_key(q: Question) -> tuple[float, int]:
            asked, correct, *_ = stats.get(q.id, (1, 0, 0, 0))
            rate = correct / asked if asked > 0 else 0.0
            return (rate, -asked)  # 正解率昇順、同率なら出題回数多い順
        sorted_by_rate = sorted(questions, key=_sort_key)
        candidates = sorted_by_rate[:count]
        selected = random.sample(candidates, len(candidates))
        desc = f"全問出題済み・正解率低い {len(selected)} 問をシャッフルで出題"

    return selected, desc



def _render_learning_calendar(user_name: str) -> None:
    """メイン画面用: 指定ユーザーの学習日をカレンダーで表示する。"""

    from streamlit_calendar import calendar as st_calendar
    from datetime import date as _date, datetime as _dt, timedelta as _timedelta

    if not user_name:
        st.info("ログインすると学習カレンダーが表示されます。")
        return

    def parse_date(k):
        try:
            return _dt.fromisoformat(str(k)).date()
        except:
            try:
                return _dt.strptime(str(k)[:10], "%Y-%m-%d").date()
            except:
                return None

    daily = get_daily_stats(user_name) or {}
    today = _date.today()

    LEARNING_DAY_THRESHOLD = 10
    learned = set()
    for k, v in daily.items():
        d = parse_date(k)
        if not d:
            continue
        total = int(v.get("total", 0)) if isinstance(v, dict) else 0
        if total >= LEARNING_DAY_THRESHOLD:
            learned.add(d)

    # --- 連続学習日数・最古/最新学習日付の表示（カレンダーの上） ---
    learned_dates = sorted(list(learned))
    streak = 0
    if learned_dates:
        streak = 1
        for i in range(len(learned_dates)-1, 0, -1):
            if (learned_dates[i] - learned_dates[i-1]).days == 1:
                streak += 1
            else:
                break
        oldest = learned_dates[0]
        newest = learned_dates[-1]
        st.caption(f"連続学習日数: {streak}日　最古の学習日: {oldest.strftime('%Y-%m-%d')}　最新の学習日: {newest.strftime('%Y-%m-%d')}")
    else:
        st.caption("学習履歴がありません。")

    # FullCalendar用イベントリスト（学習済みの日に〇マーク）
    events = []
    for d in sorted(learned):
        key_str = d.isoformat()
        v = daily.get(key_str, {})
        total = v.get("total", "?") if isinstance(v, dict) else "?"
        correct = v.get("correct", "?") if isinstance(v, dict) else "?"
        events.append({
            "title": f"〇 {correct}/{total}",
            "start": key_str,
            "allDay": True,
            "color": "#2196f3",
            "textColor": "#ffffff",
        })

    # ダークモード対応CSS
    if _is_dark_mode():
        today_bg = "#7f1d1d"
        today_text = "#ffffff"
        header_bg = "#111827"
        bg_color = "#0f172a"
        text_color = "#e5e7eb"
        border_color = "#374151"
        dow_bg = "#1e293b"
    else:
        today_bg = "#ffebee"
        today_text = "#c62828"
        header_bg = "#f8f9fa"
        bg_color = "#ffffff"
        text_color = "#212121"
        border_color = "#e0e0e0"
        dow_bg = "#f5f5f5"

    calendar_options = {
        "initialView": "dayGridMonth",
        "locale": "ja",
        "firstDay": 0,  # 日曜始まり
        "headerToolbar": {
            "left": "prev",
            "center": "title",
            "right": "next",
        },
        "height": "auto",
        "fixedWeekCount": False,
        "dayMaxEvents": True,
        "eventDisplay": "block",
        "initialDate": today.isoformat(),
    }

    custom_css = f"""
    :root {{
        --fc-border-color: {border_color};
        --fc-button-bg-color: transparent;
        --fc-button-border-color: {border_color};
        --fc-button-hover-bg-color: {dow_bg};
        --fc-button-active-bg-color: {dow_bg};
        --fc-today-bg-color: {today_bg};
        --fc-page-bg-color: {bg_color};
        --fc-neutral-bg-color: {dow_bg};
    }}
    .fc {{ color: {text_color}; background: {bg_color}; border-radius: 8px; padding: 2px; font-size: 0.78rem; }}
    .fc-toolbar {{ margin-bottom: 4px !important; }}
    .fc-toolbar-title {{ font-size: 0.95rem !important; font-weight: 700 !important; color: {text_color} !important; }}
    .fc-button {{ color: {text_color} !important; font-size: 0.85rem !important; padding: 1px 7px !important; }}
    .fc-button:focus {{ box-shadow: none !important; }}
    .fc-day-today {{ background: {today_bg} !important; }}
    .fc-day-today .fc-daygrid-day-number {{ color: {today_text} !important; font-weight: bold !important; }}
    .fc-daygrid-day-number {{ font-size: 0.72rem !important; padding: 1px 3px !important; }}
    .fc-daygrid-event {{ font-size: 0.65rem !important; border-radius: 3px !important; padding: 0 !important; }}
    .fc-col-header-cell {{ background: {dow_bg}; color: {text_color}; font-size: 0.72rem !important; padding: 2px 0 !important; }}
    .fc-scrollgrid {{ border-radius: 8px; overflow: hidden; }}
    .fc-daygrid-day {{ height: 52px !important; max-height: 52px !important; }}
    .fc-daygrid-day-frame {{ min-height: unset !important; }}
    """

    st_calendar(events=events, options=calendar_options, custom_css=custom_css, key="learning_calendar")

    # --- 統計情報 ---
    try:
        if isinstance(daily, dict) and daily:
            max_daily = max(int(v.get("total", 0)) for v in daily.values() if isinstance(v, dict))
        else:
            max_daily = 0
    except Exception:
        max_daily = 0
    st.caption(f"一日に解いた問題数（最大）: {max_daily}問")
    try:
        fastest_10 = get_fastest_time_for_count(user_name, 10) if user_name else None
        if fastest_10 is None:
            st.caption("10問の最速タイム: 記録なし")
        else:
            m = fastest_10 // 60
            s = fastest_10 % 60
            fmt = f"{m}分{s}秒" if m > 0 else f"{s}秒"
            st.caption(f"10問の最速タイム: {fmt}")
    except Exception:
        pass

    # --- ラジオボタン＋学習スタートボタン ---
    time_select = st.radio(
        "学習する日付を選択",
        options=["過去の分", "今日の分", "未来の分"],
        index=1,
        horizontal=True,
        key="time_select_radio",
    )
    if st.button("学習スタート", key="start_quiz_btn", type="primary"):
        if not st.session_state.get("user_name", ""):
            st.warning("学習を開始するにはログインしてください。")
            st.session_state.stage = "login"
            st.rerun()
        elif time_select == "今日の分":
            target_date = today
            st.session_state["override_record_date"] = target_date.strftime("%Y-%m-%d")
            st.session_state["_override_clear_on_end"] = True
            st.session_state.quiz_questions = []
            st.session_state.current_index = 0
            st.session_state.answered = False
            st.session_state.selected_index = None
            st.session_state.stage = "quiz"
            st.rerun()
        elif time_select == "過去の分":
            SEARCH_DAYS = 100
            min_date = today - _timedelta(days=SEARCH_DAYS)
            candidate_dates = [min_date + _timedelta(days=i) for i in range((today - min_date).days)]
            past_dates = []
            for dt in candidate_dates:
                if dt >= today:
                    continue
                key = dt.strftime("%Y-%m-%d")
                if int(daily.get(key, {}).get("total", 0)) < LEARNING_DAY_THRESHOLD:
                    past_dates.append(dt)
            if not past_dates:
                st.error("未学習の過去日付がありません。")
            else:
                target_date = max(past_dates)
                st.session_state["pending_start_date"] = target_date.strftime("%Y-%m-%d")
                st.session_state["pending_start_display"] = f"{target_date.month}月{target_date.day}日"
                st.session_state["pending_start_type"] = "past"
                st.rerun()
        elif time_select == "未来の分":
            SEARCH_DAYS = 100
            candidate_dates = [today + _timedelta(days=i) for i in range(1, SEARCH_DAYS + 1)]
            future_dates = []
            for dt in candidate_dates:
                key = dt.strftime("%Y-%m-%d")
                if int(daily.get(key, {}).get("total", 0)) < LEARNING_DAY_THRESHOLD:
                    future_dates.append(dt)
            if not future_dates:
                st.error("未学習の未来日付がありません。")
            else:
                target_date = min(future_dates)
                st.session_state["pending_start_date"] = target_date.strftime("%Y-%m-%d")
                st.session_state["pending_start_display"] = f"{target_date.month}月{target_date.day}日"
                st.session_state["pending_start_type"] = "future"
                st.rerun()

    # --- pending_start_date があれば確認ダイアログを表示 ---
    if st.session_state.get("pending_start_date"):
        pd_str = st.session_state.get("pending_start_display", st.session_state.get("pending_start_date"))
        st.warning(f"{pd_str}の分を学習しますか？")
        col_yes, col_no = st.columns([1, 1])
        with col_yes:
            if st.button("はい", key="confirm_start_yes"):
                try:
                    target_iso = st.session_state.pop("pending_start_date")
                except Exception:
                    target_iso = None
                if target_iso:
                    st.session_state["override_record_date"] = target_iso
                    st.session_state["_override_clear_on_end"] = True
                    st.session_state.quiz_questions = []
                    st.session_state.current_index = 0
                    st.session_state.answered = False
                    st.session_state.selected_index = None
                    st.session_state.stage = "quiz"
                    st.session_state.pop("pending_start_display", None)
                    st.session_state.pop("pending_start_type", None)
                st.rerun()
        with col_no:
            if st.button("キャンセル", key="confirm_start_no"):
                st.session_state.pop("pending_start_date", None)
                st.session_state.pop("pending_start_display", None)
                st.session_state.pop("pending_start_type", None)
                st.rerun()



def _reload_db_from_input() -> None:
    imported_count = reload_db_from_csvs(INPUT_DIR, DB_PATH)
    reloaded_questions = load_questions_from_db(DB_PATH)
    # デフォルトタグをリセットして再適用
    set_default_tags([])
    set_default_question_tags({})
    _apply_default_tags()
    st.session_state["_default_tags_applied"] = True
    restart()
    st.session_state.reload_notice = (
        f"DBをクリアして再読込しました（取込CSV: {imported_count}件 / 問題数: {len(reloaded_questions)}件）"
    )


def _reset_answer_history_only() -> None:
    # Determine which user to reset:
    # Prefer the actively-logged-in user (st.session_state['user_name']).
    # If no user is logged in but the login screen has a selection, the selectbox value
    # is stored in "login_selected_user" for use here.
    user_name = st.session_state.get("user_name", "") or st.session_state.get("login_selected_user", "")
    if not user_name:
        st.warning("リセット対象のユーザーが選択されていません。ユーザーを選んでから再度お試しください。")
        return
    reset_user_stats(user_name)
    # Persist immediately to LocalStorage so the change is visible right away
    try:
        save_app_data(LS)
    except Exception:
        pass
    st.session_state.reload_notice = f"「{user_name}」の学習成績をリセットしました。"


def render_setup(all_questions: list[Question]) -> None:
    # 上部のタイトルは出題画面では表示しない（UIをコンパクトにするため）
    # st.title("English Quiz")

    # 画面上部にテーマ切替ボタンを表示
    render_theme_toggle()

    # 学習カレンダーを表示（ログインユーザーの学習状況）
    user_name = st.session_state.get("user_name", "")
    _render_learning_calendar(user_name)

    # 保存確認メッセージ（直近に詳細設定を保存した場合に表示）
    # 表示内容は簡潔にする（詳細な設定オブジェクトは表示しない）
    if st.session_state.get('last_saved_user_settings'):
        try:
            info_user = st.session_state.get('user_name', '') or st.session_state.get('login_selected_user', '')
            st.success(f"詳細設定をユーザー「{info_user}」に保存しました。")
            # do not display the raw settings dict
        except Exception:
            pass

    # 詳細設定の表示切替（チェックボックスで表示/非表示を切替）
    # チェック状態は st.session_state['show_detail_settings'] に保持されます
    st.checkbox("詳細設定を表示", value=st.session_state.get("show_detail_settings", False), key="show_detail_settings")
    # チェックを外したときに（詳細設定非表示時）ウィジェットが存在しないため
    # 出題モードの表示がデフォルトに戻ることがある。ここで保存済みの
    # user_saved_order_mode を優先して session_state['order_mode'] に反映する。
    try:
        if not st.session_state.get("show_detail_settings", False):
            preferred = st.session_state.get('user_saved_order_mode', None)
            if preferred in ORDER_MODE_OPTIONS:
                st.session_state['order_mode'] = preferred
            else:
                # フォールバック: 現在の session の order_mode を壊さないように
                st.session_state.setdefault('order_mode', "おすすめ")
    except Exception:
        pass

    # クイズ画面専用のフォントサイズ調整（問題文・選択肢を大きめに）
    if st.session_state.get('show_detail_settings', False):
        # 設定フォーム（出題モード・日本語表示・音声モード・出題数）
        # Ensure the radio widget for order_mode has a sensible initial value
        # Prefer a session-only persisted choice ('user_saved_order_mode') if present,
        # otherwise fall back to any existing session 'order_mode' or the default.
        desired_order = st.session_state.get('user_saved_order_mode', st.session_state.get('order_mode', "おすすめ"))
        if 'order_mode' not in st.session_state or st.session_state.get('order_mode') not in ORDER_MODE_OPTIONS:
            # Set default before widget creation so the radio reflects the persisted choice
            st.session_state['order_mode'] = desired_order

        with st.form("detail_settings_form"):
            # Force the initial selected index to the effective order mode so
            # the radio visual never falls back to the first option due to
            # widget initialization timing.
            try:
                cur_val = st.session_state.get('order_mode', desired_order)
                idx = ORDER_MODE_OPTIONS.index(cur_val) if cur_val in ORDER_MODE_OPTIONS else 0
            except Exception:
                idx = 0
            order_mode = st.radio(
                "出題モード",
                options=ORDER_MODE_OPTIONS,
                index=idx,
                horizontal=True,
                key="order_mode",
                help="おすすめ：未出題問題を優先。全問済みなら正解率の低い問題をシャッフル出題",
            )
            # Immediately reflect the widget-selected value into a session-only
            # saved key so transient LocalStorage pushes (which may contain
            # older data) won't temporarily overwrite the user's interactive
            # selection before they press "設定を適用".
            try:
                cur = st.session_state.get('order_mode')
                if cur in ORDER_MODE_OPTIONS:
                    st.session_state['user_saved_order_mode'] = cur
            except Exception:
                pass
            show_japanese = st.checkbox("日本語を表示する", value=st.session_state.show_japanese)
            voice_mode = st.checkbox("🔊 音声モード（自動読み上げ）", value=st.session_state.get("voice_mode", False))
            st.session_state.voice_mode = voice_mode
            st.session_state.voice_repeat = 1
            # 時間制限は廃止されたためフォームでは設定しない
            count_mode = st.radio(
                "出題数",
                options=["10問", "20問", "30問", "50問", "全部"],
                horizontal=True,
            )

            # 少し間を空ける
            st.markdown("<br>", unsafe_allow_html=True)

            # フォーム内に「設定を適用」と「🏷️ タグ管理」の2つの送信ボタンを配置
            c1, c2 = st.columns([1, 1])
            with c1:
                submitted = st.form_submit_button("設定を適用")
            with c2:
                tag_manage_submit = st.form_submit_button("🏷️ タグ管理", key="tag_manage_submit")
            if tag_manage_submit:
                # フォーム送信（タグ管理） → タグ管理画面へ遷移（設定の適用は行わない）
                st.session_state.stage = "tag_manage"
                st.rerun()
            if submitted:
                # The radio/checkbox widgets already update session_state for keys
                # (e.g. `order_mode` via key="order_mode"), assigning them
                # again here can cause Streamlit to raise an exception in some
                # environments. Only set keys that are not managed by widgets.
                st.session_state['show_japanese'] = show_japanese
                st.session_state['voice_mode'] = voice_mode
                st.session_state['count_mode'] = count_mode
                # Persist detailed settings per-user when applied
                try:
                    user_name = st.session_state.get("user_name", "") or st.session_state.get("login_selected_user", "")
                    if user_name:
                        # Prefer the widget-managed session value for order_mode and
                        # validate it before persisting. Using the local `order_mode`
                        # variable can be subject to timing/synchronization issues
                        # with Streamlit widgets; prefer session_state which the
                        # widget updates directly (via key="order_mode").
                        stored_order_mode = st.session_state.get('order_mode', order_mode)
                        if stored_order_mode not in ORDER_MODE_OPTIONS:
                            # Fall back to a safe default rather than persisting an
                            # invalid value.
                            stored_order_mode = "おすすめ"

                        settings = {
                            'order_mode': stored_order_mode,
                            'show_japanese': show_japanese,
                            'voice_mode': voice_mode,
                            'count_mode': count_mode,
                            'voice_repeat': st.session_state.get('voice_repeat', 1),
                            'setup_sel_user_tags': st.session_state.get('setup_sel_user_tags', []),
                            'setup_sel_default_tags': st.session_state.get('setup_sel_default_tags', []),
                            'setup_sel_system_tags': st.session_state.get('setup_sel_system_tags', []),
                            'setup_sel_diff_tags': st.session_state.get('setup_sel_diff_tags', []),
                            'setup_include_untagged': st.session_state.get('setup_include_untagged', False),
                        }
                        # Debug log writing removed to avoid creating local debug files.
                        set_user_settings(user_name, settings)
                        try:
                            save_app_data(LS)
                        except Exception:
                            pass
                        # 確認用: 保存した設定をセッションに保持して表示できるようにする
                        try:
                            saved_settings = get_user_settings(user_name)
                            st.session_state['last_saved_user_settings'] = saved_settings
                            st.session_state['reload_notice'] = f"設定をユーザー「{user_name}」に保存しました。"
                            # Also keep a session-only copy to prefer over any
                            # asynchronous LocalStorage pushes that may contain
                            # older data. This prevents race conditions where the
                            # browser LocalStorage component may later overwrite
                            # the in-memory session value with stale state.
                            try:
                                stored_ord = saved_settings.get('order_mode') if isinstance(saved_settings, dict) else None
                                if stored_ord in ORDER_MODE_OPTIONS:
                                    st.session_state['user_saved_order_mode'] = stored_ord
                            except Exception:
                                pass
                        except Exception:
                            st.session_state['reload_notice'] = f"設定をユーザー「{user_name}」に保存しました（確認情報の取得に失敗）。"
                except Exception:
                    pass
                st.rerun()

        # フォーム外でタグ絞り込みUIを表示する（フォーム内にボタンを置くと Streamlit が例外を投げるため）
        # タグ群の取得
        all_tags = _get_combined_tags()
        question_tags = _get_combined_question_tags()
        user_tags = get_all_tags()
        default_tags = get_default_tags()
        system_tags = get_system_tags()
        diff_qt = _get_difficulty_question_tags()
        diff_tags = sorted({t for tags in diff_qt.values() for t in tags})

        with st.expander("タグで絞り込み", expanded=False):
            # ── ユーザータグ ──
            st.markdown("**🏷️ ユーザータグ**")
            if user_tags:
                cur = list(st.session_state.get("setup_sel_user_tags", []))
                cols = st.columns(min(4, len(user_tags)))
                for i, t in enumerate(user_tags):
                    col = cols[i % len(cols)]
                    label = f"✅ #{t}" if f"#{t}" in cur else f"#{t}"
                    if col.button(label, key=f"setup_user_btn_{t}"):
                        _toggle_selection("setup_sel_user_tags", f"#{t}")
                        st.rerun()
            else:
                st.caption("ユーザータグがありません")

            st.divider()

            # ── デフォルトタグ ──
            st.markdown("**📋 デフォルトタグ**")
            if default_tags:
                cur = list(st.session_state.get("setup_sel_default_tags", []))
                cols = st.columns(min(4, len(default_tags)))
                for i, t in enumerate(default_tags):
                    col = cols[i % len(cols)]
                    label = f"✅ #{t}" if f"#{t}" in cur else f"#{t}"
                    if col.button(label, key=f"setup_default_btn_{t}"):
                        _toggle_selection("setup_sel_default_tags", f"#{t}")
                        st.rerun()
            else:
                st.caption("デフォルトタグがありません")

            st.divider()

            # ── システムタグ ──
            st.markdown("**⚙️ システムタグ**")
            if system_tags:
                cur = list(st.session_state.get("setup_sel_system_tags", []))
                cols = st.columns(min(4, len(system_tags)))
                for i, t in enumerate(system_tags):
                    col = cols[i % len(cols)]
                    label = f"✅ #{t}" if f"#{t}" in cur else f"#{t}"
                    if col.button(label, key=f"setup_system_btn_{t}"):
                        _toggle_selection("setup_sel_system_tags", f"#{t}")
                        st.rerun()
            else:
                st.caption("システムタグがありません")

            st.divider()

            # ── 難易度タグ ──
            st.markdown("**🎯 難易度タグ**")
            if diff_tags:
                cur = list(st.session_state.get("setup_sel_diff_tags", []))
                cols = st.columns(min(4, len(diff_tags)))
                for i, t in enumerate(diff_tags):
                    col = cols[i % len(cols)]
                    label = f"✅ #{t}" if f"#{t}" in cur else f"#{t}"
                    if col.button(label, key=f"setup_diff_btn_{t}"):
                        _toggle_selection("setup_sel_diff_tags", f"#{t}")
                        st.rerun()
            else:
                st.caption("難易度タグがありません")

            st.divider()

            st.checkbox("タグ無しを含める", key="setup_include_untagged")
    else:
        # デフォルト値を使う（詳細設定を表示していない通常表示時）
        # ウィジェットの値や保存値の適用は画面中央で一元的に決定するため
        # ここでは表示関連のフラグのみ取得する。
        show_japanese = st.session_state.get('show_japanese', False)
        voice_mode = st.session_state.get('voice_mode', False)
        count_mode = st.session_state.get('count_mode', "10問")

    # タグで出題範囲を絞り込みのUIは詳細設定内に移動したためここでは省略
    all_tags = _get_combined_tags()
    question_tags = _get_combined_question_tags()
    user_tags = get_all_tags()
    default_tags = get_default_tags()
    system_tags = get_system_tags()
    diff_qt = _get_difficulty_question_tags()
    diff_tags = sorted({t for tags in diff_qt.values() for t in tags})

    # 選択されたフィルタに基づき対象問題を決定（OR条件）
    selected_tags = set()
    for v in (
        st.session_state.get("setup_sel_user_tags", []),
        st.session_state.get("setup_sel_default_tags", []),
        st.session_state.get("setup_sel_system_tags", []),
        st.session_state.get("setup_sel_diff_tags", []),
    ):
        for s in v:
            if s.startswith("#"):
                selected_tags.add(s[1:])

    if not selected_tags and not st.session_state.get("setup_include_untagged", False):
        target_questions = all_questions
    else:
        target_questions = []
        for q in all_questions:
            qid = str(q.id)
            q_tags = question_tags.get(qid, [])
            if st.session_state.get("setup_include_untagged", False) and not q_tags:
                target_questions.append(q)
                continue
            if selected_tags and any(t in q_tags for t in selected_tags):
                target_questions.append(q)

    # --- 出題数・モード・ボタンUIは詳細設定フォームとカレンダー上部に移動済み ---
    preset_map = {"10問": 10, "20問": 20, "30問": 30, "50問": 50}
    question_count = preset_map.get(count_mode, len(target_questions))
    # Determine effective order_mode (centralized) to avoid races between
    # widget-managed 'order_mode' and persisted 'user_saved_order_mode'.
    order_mode = _effective_order_mode()
    # Debug log writing removed to avoid creating local debug files.

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
            user_name = st.session_state.get("user_name", "")
            stats = get_question_stats(user_name)
            pool = sorted(
                target_questions,
                key=lambda q: stats.get(q.id, (0, 0, 0))[0],
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

    # --- 成績リスト・タグ管理ボタンはそのまま ---
    if st.button("これまでの成績リストを表示"):
        st.session_state.stage = "history"
        st.rerun()

    # ── 習得済み ──

    # georgeでログイン時のみ管理用のボタンを表示（成績リセットはログイン画面下部のみに移動）
    is_george = st.session_state.get("user_name", "").lower() == "george"
    if is_george:
        # 管理機能: 正解データをCSVに反映（廃止予定の機能の仮実装）
        col1, col2, col3 = st.columns(3)
        with col3:
            if st.button("正解データをCSVに反映"):
                try:
                    # 仮実装: 実際の関数が必要ならimportしてください
                    updated = 0  # export_correct_answers_to_csvs(INPUT_DIR, DB_PATH)
                    st.session_state.reload_notice = f"正解データをCSVに反映しました（更新ファイル: {updated}件）"
                except Exception as exc:
                    st.error(f"CSV反映に失敗しました: {exc}")
                else:
                    st.rerun()

    # (成績シェア用メールアドレス設定はログイン画面の一番下に移動しました)

    _render_back_to_login_button()


def _rate_bar(rate: float) -> str:
    # 正解率に応じた色付きバーをHTMLで返す。
    if _is_dark_mode():
        if rate < 0.5:
            bar_color = "#7f1d1d"  # 暗い赤系
        elif rate < 0.8:
            bar_color = "#7c2d12"  # 暗い橙系
        else:
            bar_color = "#1e3a8a"  # 暗い青系
        track_color = "#1f2937"
        text_color = "#d1d5db"
    else:
        if rate < 0.5:
            bar_color = "#e57373"  # 赤系
        elif rate < 0.8:
            bar_color = "#ffb74d"  # 橙系
        else:
            bar_color = "#64b5f6"  # 青系
        track_color = "#e0e0e0"
        text_color = "inherit"
    pct = f"{rate * 100:.0f}%"
    return (
        f"<span style='display:inline-block;width:60px;height:10px;"
        f"background:{track_color};border-radius:5px;vertical-align:middle;'>"
        f"<span style='display:inline-block;width:{pct};height:10px;"
        f"background:{bar_color};border-radius:5px;'></span></span>"
        f"&nbsp;<small style='color:{text_color};'>{rate*100:.1f}%</small>"
    )


_CAT1_ORDER = ["基本演習", "標準演習", "応用演習"]


def _sorted_cat1(keys: list[str]) -> list[str]:
    return sorted(keys, key=lambda c: (_CAT1_ORDER.index(c) if c in _CAT1_ORDER else len(_CAT1_ORDER), c))



def _render_all_questions_tree() -> None:
    all_questions = load_questions_from_db(DB_PATH)
    user_name = st.session_state.get("user_name", "")
    stats = get_question_stats(user_name)  # {question_id: (asked, correct, incorrect)}
    question_tags = _get_combined_question_tags()
    all_tags = _get_combined_tags()

    if not all_questions:
        st.info("問題がありません。")
        return

    # タグごとにグルーピング（複数タグがある問題は各タグに重複表示）
    tag_groups: dict[str, list[Question]] = {}
    for tag in all_tags:
        tag_groups[tag] = []
    tag_groups["タグ無し"] = []

    for q in all_questions:
        qid = str(q.id)
        q_tags = question_tags.get(qid, [])
        if not q_tags:
            tag_groups["タグ無し"].append(q)
        else:
            for tag in q_tags:
                if tag in tag_groups:
                    tag_groups[tag].append(q)

    # 表示順: 定義済みタグ → 未タグ
    display_order = all_tags + ["タグ無し"]

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
                choices = [q.choice1, q.choice2, q.choice3, q.choice4]
                choices_html = " / ".join(
                    f"<b>{html.escape(c)}</b>" if i + 1 == q.answer else html.escape(c)
                    for i, c in enumerate(choices) if c
                )
                if q.id in stats:
                    asked, correct, incorrect, *_ = stats[q.id]
                    rate = correct / asked if asked > 0 else 0.0
                    if _is_dark_mode():
                        bg_color = "#2b1111" if rate < 0.5 else ("#2a1b0b" if rate < 0.8 else "#0b1f33")
                        item_text_color = "#d1d5db"
                        sub_text_color = "#9ca3af"
                        item_border = "border:1px solid #374151;"
                    else:
                        bg_color = "#fdecec" if rate < 0.5 else ("#fff8e6" if rate < 0.8 else "#e6f4ff")
                        item_text_color = "inherit"
                        sub_text_color = "#555555"
                        item_border = ""
                    item_bar = _rate_bar(rate)
                    html_parts.append(
                        f"<div style='background:{bg_color};color:{item_text_color};{item_border}padding:0.45rem 0.7rem;"
                        "border-radius:6px;margin-bottom:0.25rem;white-space:pre-wrap;line-height:1.5;'>"
                        f"{english_text}<br>"
                        f"<small style='color:{sub_text_color};'>選択肢: {choices_html}</small><br>"
                        f"<small>{item_bar}&nbsp;|&nbsp;"
                        f"正解: {correct} / 不正解: {incorrect} / 計: {asked} 回</small>"
                        "</div>"
                    )
                else:
                    if _is_dark_mode():
                        unasked_bg = "#111827"
                        unasked_text = "#9ca3af"
                        unasked_sub = "#6b7280"
                        unasked_border = "border:1px solid #374151;"
                    else:
                        unasked_bg = "#f0f0f0"
                        unasked_text = "#888888"
                        unasked_sub = "#999999"
                        unasked_border = ""
                    html_parts.append(
                        f"<div style='background:{unasked_bg};padding:0.45rem 0.7rem;"
                        f"border-radius:6px;margin-bottom:0.25rem;white-space:pre-wrap;{unasked_border}"
                        f"line-height:1.5;color:{unasked_text};'>"
                        f"{english_text}<br>"
                        f"<small style='color:{unasked_sub};'>選択肢: {choices_html}</small><br>"
                        "<small>未出題</small>"
                        "</div>"
                    )
            st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_login() -> None:
    st.title("📘 English Quiz")
    # 画面上部にテーマ切替ボタンを表示
    render_theme_toggle()
    # ログイン画面でテーマを選択（ローカルに保存して即時反映）
    try:
        current_forced = st.session_state.get("forced_theme", None)
        default_idx = 0 if (current_forced is None or current_forced == "light") else 1
        theme_choice = st.radio("表示テーマ", options=["ライト", "ダーク"], horizontal=True, index=default_idx, key="login_theme_radio")
        if st.button("適用", key="theme_apply_btn"):
            selected_theme = "light" if theme_choice == "ライト" else "dark"
            if st.session_state.get("forced_theme") != selected_theme:
                st.session_state["forced_theme"] = selected_theme
                try:
                    save_app_data(LS)
                except Exception:
                    pass
                st.rerun()
    except Exception:
        # 安全性: 何か問題があってもログイン表示を妨げない
        pass

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
        # Keep the current selection available in session so other controls (reset etc.)
        # can reference the selected user even if the user hasn't clicked "ログイン".
        st.session_state["login_selected_user"] = selected_user

        col_login, col_delete = st.columns([2, 1])
        with col_login:
            if st.button("ログイン", type="primary"):
                st.session_state["user_name"] = selected_user
                set_last_user(selected_user)
                # Load per-user saved detailed settings (if any) into session
                try:
                    saved = get_user_settings(selected_user) or {}
                    # Only set known keys to avoid clobbering session
                    for k in (
                        'order_mode', 'show_japanese', 'voice_mode', 'count_mode', 'voice_repeat',
                        'setup_sel_user_tags', 'setup_sel_default_tags', 'setup_sel_system_tags', 'setup_sel_diff_tags', 'setup_include_untagged'
                    ):
                        if k in saved:
                            # Validate loaded order_mode: do not inject invalid values
                            # into session_state because that can lead to UI/runtime
                            # inconsistencies later. For other keys, restore as-is.
                            if k == 'order_mode':
                                try:
                                    if saved[k] in ORDER_MODE_OPTIONS:
                                        # Don't overwrite the widget-managed 'order_mode'
                                        # key directly during login. Instead set the
                                        # session-only 'user_saved_order_mode' so UI
                                        # rendering and later preparation logic can
                                        # prefer this persisted choice without
                                        # clobbering live widget state.
                                        st.session_state['user_saved_order_mode'] = saved[k]
                                except Exception:
                                    # If saved[k] is malformed, ignore it.
                                    pass
                            else:
                                st.session_state[k] = saved[k]
                except Exception:
                    pass
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

    # (READMEは画面一番下に移動しました)

    # --- 学習成績をリセットボタンを画面一番下に移動 ---
    st.divider()
    if st.button("学習成績をリセット", key="reset_score_btn"):
        st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset", False):
        st.warning("本当にリセットしますか？ パスワードを入力してください。")
        confirm_pw = st.text_input(
            "パスワードを入力",
            type="password",
            key="reset_confirm_input_login",
        )
        rc1, rc2 = st.columns(2)
        with rc1:
            if st.button("リセット実行", key="reset_exec_btn_login"):
                if confirm_pw.strip() == "1234":
                    try:
                        _reset_answer_history_only()
                    except Exception as exc:
                        st.error(f"成績リセットに失敗しました: {exc}")
                        st.session_state["confirm_reset"] = False
                    else:
                        st.session_state["confirm_reset"] = False
                        st.rerun()
                else:
                    st.error("パスワードが一致しません。リセットを中止しました。")
        with rc2:
            if st.button("キャンセル", key="reset_cancel_btn_login"):
                st.session_state["confirm_reset"] = False
                st.rerun()

    # ── シェア用メールアドレス設定（画面一番下） ──
    st.divider()
    with st.expander("📧 成績シェア用メールアドレス"):
        # Prefer the actively-logged-in user; if not logged-in, use the selected user in the login selectbox
        target_user = st.session_state.get("user_name", "") or st.session_state.get("login_selected_user", "")
        if not target_user:
            st.caption("ユーザーを選択またはログインすると、ここに登録済みのメールアドレスが表示されます。")
        else:
            current_emails = get_share_emails(target_user) or []
            if current_emails:
                st.write("登録済み: " + ", ".join(current_emails))
                del_email = st.selectbox("削除するアドレス", options=current_emails, key="del_share_email")
                if st.button("このアドレスを削除", key="del_share_email_btn"):
                    new_list = [e for e in current_emails if e != del_email]
                    set_share_emails(target_user, new_list)
                    try:
                        save_app_data(LS)
                    except Exception:
                        pass
                    st.rerun()
            else:
                st.caption("メールアドレスが登録されていません。")

            with st.form("add_share_email_form", clear_on_submit=True):
                new_email = st.text_input("メールアドレスを追加", placeholder="example@mail.com", key="add_share_email_input")
                if st.form_submit_button("追加"):
                    addr = (new_email or "").strip()
                    if addr and "@" in addr:
                        if addr not in current_emails:
                            current_emails.append(addr)
                            set_share_emails(target_user, current_emails)
                            try:
                                save_app_data(LS)
                            except Exception:
                                pass
                            st.rerun()
                        else:
                            st.warning("このアドレスは既に登録されています。")
                    else:
                        st.error("有効なメールアドレスを入力してください。")

    # ── README表示（画面最下部） ──
    st.divider()
    with st.expander("📖 README（利用規約・免責事項）"):
        readme_path = Path(__file__).parent / "README.md"
        if readme_path.exists():
            st.markdown(readme_path.read_text(encoding="utf-8"), unsafe_allow_html=False)
        else:
            st.caption("README.md が見つかりません。")

def render_history() -> None:
    st.title("成績リスト")
    # テーマ切替ボタン
    render_theme_toggle()
    # 日別正解率の推移グラフ
    try:
        # グラフ表示は無効化しました（表示すると多すぎるため）。
        # 日別統計データは内部的に保持しますが、グラフは表示しません。
        # もし将来的にグラフを復活させる場合はここに描画ロジックを追加してください。
        pass
    except Exception:
        pass

    _render_all_questions_tree()

    # ── 正解率100%未満の問題をメールで送信 ──
    all_questions = load_questions_from_db(DB_PATH)
    user_name = st.session_state.get("user_name", "")
    stats = get_question_stats(user_name)

    # 正解率 < 100% の問題を抽出し、正解率が低い順にソート
    incomplete: list[tuple[float, int, int, int, str]] = []  # (rate, asked, correct, incorrect, text)
    for q in all_questions:
        if q.id in stats:
            asked, correct, incorrect, *_ = stats[q.id]
            if asked > 0:
                rate = correct / asked
                if rate < 1.0:
                    incomplete.append((rate, asked, correct, incorrect, q.english or ""))
    incomplete.sort(key=lambda x: (x[0], -x[1]))  # 正解率昇順、同率なら出題回数多い順

    if incomplete:
        st.divider()
        st.subheader("📧 正解率100%未満の問題をメールで送信")
        import urllib.parse as _urlparse
        _lines: list[str] = []
        _lines.append(f"正解率100%未満の問題一覧 ({len(incomplete)}問)")
        _lines.append("")
        for i, (rate, asked, correct, incorrect, text) in enumerate(incomplete, 1):
            _lines.append(f"{i}. [{rate*100:.0f}%] (正解{correct}/不正解{incorrect}/計{asked}回) {text}")
        _mail_body = "\n".join(_lines)
        _mail_subject = f"Quiz復習リスト: 正解率100%未満 {len(incomplete)}問"
        _to_addrs = ",".join(get_share_emails(user_name))
        _mailto_url = f"mailto:{_urlparse.quote(_to_addrs)}?subject={_urlparse.quote(_mail_subject)}&body={_urlparse.quote(_mail_body)}"
        # 送信用の mailto リンクをボタン風に表示
        # 受信先アドレスが未設定の場合は宛先空欄のメール作成画面を開きます。
        display_addr = _to_addrs if _to_addrs else "（未設定）"
        st.caption(f"送信先: {display_addr}")
        try:
            st.markdown(
                f'<a href="{_mailto_url}" onclick="window.location.href=this.href;return false;" '
                f'style="display:inline-block;padding:0.5rem 1rem;background:{_theme_color("#2563eb","#1e3a8a")};color:{_theme_text_color("#ffffff","#f3f4f6")};border-radius:8px;text-decoration:none;">'
                f'📧 正解率100%未満の問題をメールで送信 ({len(incomplete)}問)</a>',
                unsafe_allow_html=True,
            )
        except Exception:
            # 安全にフォールバックして単純なリンクを表示
            st.write(f"送信用URL: {_mailto_url}")
    else:
        st.info("正解率100%未満の問題はありません。")

    if st.button("メイン画面に戻る", type="primary"):
        st.session_state.stage = "setup"
        st.rerun()

    _render_back_to_login_button()


def render_tag_manage() -> None:
    # タグ管理画面：どの問題にどのハッシュタグが付いているかを一覧・編集できる。
    st.title("🏷️ タグ管理")
    # テーマ切替ボタン
    render_theme_toggle()

    all_questions = load_questions_from_db(DB_PATH)
    user_tags = get_all_tags()
    user_question_tags = get_question_tags()
    default_tags = get_default_tags()
    default_question_tags = get_default_question_tags()
    system_tags = get_system_tags()
    system_question_tags = get_system_question_tags()
    combined_tags = _get_combined_tags()
    combined_question_tags = _get_combined_question_tags()

    if st.button("メイン画面に戻る", type="primary", key="tag_manage_back"):
        st.session_state.stage = "setup"
        st.rerun()

    # ── タグ一覧 ──
    st.subheader("タグ一覧")
    if user_tags:
        st.write("🏷️ ユーザータグ：" + "　".join([f"`#{t}`" for t in user_tags]))
    if default_tags:
        st.write("📋 デフォルトタグ：" + "　".join([f"`#{t}`" for t in default_tags]))
    if system_tags:
        st.write("⚙️ システムタグ：" + "　".join([f"`#{t}`" for t in system_tags]))
    _diff_qt = _get_difficulty_question_tags()
    _active_diff_tags = sorted({t for tags in _diff_qt.values() for t in tags})

    if not combined_tags:
        st.caption("タグを作成すると、ここに問題×タグの表が表示されます。")
        return

    import pandas as pd
    rows = []
    for q in all_questions:
        qid = str(q.id)
        q_tags = combined_question_tags.get(qid, [])
        row: dict = {
            "No": len(rows) + 1,
            "問題文": (q.english or "(No English text)")[:80],
        }
        for tag in combined_tags:
            row[f"#{tag}"] = "✅" if tag in q_tags else ""
        rows.append(row)

    df = pd.DataFrame(rows)

    event = st.dataframe(
        df,
        column_config={
            "No": st.column_config.NumberColumn("No", width="small"),
            "問題文": st.column_config.TextColumn("問題文", width="large"),
        },
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tag_table_select",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        sel_idx = selected_rows[0]
        sel_q = all_questions[sel_idx]
        sel_qid = str(sel_q.id)
        sel_text = sel_q.english or "(No English text)"

        st.info(f"**#{sel_idx + 1}**: {sel_text}")

        # ユーザータグ（1行目・編集可能）
        if user_tags:
            st.caption("🏷️ ユーザータグ")
            current_user_tags = user_question_tags.get(sel_qid, [])
            ut_cols = st.columns(min(len(user_tags), 6))
            for i, tag in enumerate(user_tags):
                col = ut_cols[i % len(ut_cols)]
                is_on = tag in current_user_tags
                label = f"✅ #{tag}" if is_on else f"#{tag}"
                if col.button(label, key=f"tm_utag_{sel_qid}_{tag}"):
                    if is_on:
                        new_tags = [t for t in current_user_tags if t != tag]
                    else:
                        new_tags = current_user_tags + [tag]
                    if new_tags:
                        user_question_tags[sel_qid] = new_tags
                    elif sel_qid in user_question_tags:
                        del user_question_tags[sel_qid]
                    set_question_tags(user_question_tags)
                    try:
                        save_app_data(LS)
                    except Exception:
                        pass
                    st.rerun()

        # デフォルトタグ（2行目・読み取り専用）
        if default_tags:
            st.caption("📋 デフォルトタグ（CSV由来・読み取り専用）")
            dt_tags = default_question_tags.get(sel_qid, [])
            st.write("　".join([f"✅ `#{t}`" if t in dt_tags else f"`#{t}`" for t in default_tags]))

        # システムタグ（3行目）
        if system_tags:
            st.caption("⚙️ システムタグ")
            current_sys_tags = system_question_tags.get(sel_qid, [])
            st_cols = st.columns(min(len(system_tags), 6))
            for i, tag in enumerate(system_tags):
                col = st_cols[i % len(st_cols)]
                is_on = tag in current_sys_tags
                label = f"✅ #{tag}" if is_on else f"#{tag}"
                if col.button(label, key=f"tm_stag_{sel_qid}_{tag}"):
                    if is_on:
                        new_tags = [t for t in current_sys_tags if t != tag]
                    else:
                        new_tags = current_sys_tags + [tag]
                    if new_tags:
                        system_question_tags[sel_qid] = new_tags
                    elif sel_qid in system_question_tags:
                        del system_question_tags[sel_qid]
                    set_system_question_tags(system_question_tags)
                    st.rerun()

        # 難易度タグ（4行目・読み取り専用）
        _sel_diff_tags = _get_difficulty_question_tags().get(sel_qid, [])
        if _sel_diff_tags:
            st.caption("🎯 難易度タグ（CSV由来・読み取り専用）")
            st.write("　".join([f"✅ `#{t}`" for t in _sel_diff_tags]))

    else:
        st.caption("👆 テーブルの行をクリックすると、タグを編集できます。")

    _render_back_to_login_button()


# --- 未定義補助関数の仮実装（先頭に移動） ---
def _update_system_tags_on_answer(question_id: int, is_correct: bool) -> None:
    # システムタグの自動付与等が必要な場合はここで実装
    pass

def _apply_default_tags() -> None:
    # デフォルトタグの再適用処理（必要に応じて実装）
    pass

def _get_combined_tags() -> list[str]:
    # ユーザー・デフォルト・システムタグを統合したリストを返す
    tags = set(get_all_tags())
    tags.update(get_default_tags())
    tags.update(get_system_tags())
    # 難易度タグも含める
    try:
        diff_qt = _get_difficulty_question_tags()
        diff_tags = {t for tags in diff_qt.values() for t in tags}
        tags.update(diff_tags)
    except Exception:
        # 何か失敗しても他のタグに影響を与えない
        pass
    return sorted(tags)

def _get_combined_question_tags() -> dict[str, list[str]]:
    # 各種タグのマージ（ユーザー・デフォルト・システム）
    qtags = get_question_tags().copy()
    for k, v in get_default_question_tags().items():
        qtags.setdefault(k, []).extend([t for t in v if t not in qtags.get(k, [])])
    for k, v in get_system_question_tags().items():
        qtags.setdefault(k, []).extend([t for t in v if t not in qtags.get(k, [])])
    # 難易度タグをマージ（CSV由来・読み取り専用）
    try:
        for k, v in _get_difficulty_question_tags().items():
            qtags.setdefault(k, []).extend([t for t in v if t not in qtags.get(k, [])])
    except Exception:
        pass
    # 重複除去
    for k in qtags:
        qtags[k] = list(sorted(set(qtags[k])))
    return qtags

def _get_difficulty_question_tags() -> dict[str, list[str]]:
    # DBから難易度情報を読み取り、各問題IDに対して難易度タグリストを返す
    # 例: difficulty=3 -> ["難易度★★★"]
    try:
        from quiz_logic import load_difficulty_tags

        diffs = load_difficulty_tags(DB_PATH)  # {question_id: difficulty}
        result: dict[str, list[str]] = {}
        for qid, diff in diffs.items():
            try:
                d = int(diff)
            except Exception:
                continue
            if d <= 0:
                continue
            # Build difficulty tag like: 難易度★★★
            tag = "難易度" + ("★" * d)
            result[str(qid)] = [tag]
        return result
    except Exception:
        return {}


def _prepare_quiz_questions(all_questions: list[Question]) -> list[Question]:
    """セッション内の設定（タグ選択・出題モード・出題数など）に基づき
    出題用の問題リストを作成して返す。主にカレンダーから直接クイズを開始する
    場合など、render_setup を経由せずに render_quiz で問題が必要になったときに使う。
    """
    # 選択されたフィルタに基づき対象問題を決定（render_setup と同じロジック）
    all_tags = _get_combined_tags()
    question_tags = _get_combined_question_tags()

    selected_tags = set()
    for v in (
        st.session_state.get("setup_sel_user_tags", []),
        st.session_state.get("setup_sel_default_tags", []),
        st.session_state.get("setup_sel_system_tags", []),
        st.session_state.get("setup_sel_diff_tags", []),
    ):
        for s in v:
            if isinstance(s, str) and s.startswith("#"):
                selected_tags.add(s[1:])

    if not selected_tags and not st.session_state.get("setup_include_untagged", False):
        target_questions = all_questions
    else:
        target_questions = []
        for q in all_questions:
            qid = str(q.id)
            q_tags = question_tags.get(qid, [])
            if st.session_state.get("setup_include_untagged", False) and not q_tags:
                target_questions.append(q)
                continue
            if selected_tags and any(t in q_tags for t in selected_tags):
                target_questions.append(q)

    # 出題数・モード設定を読む
    # Use centralized effective selection to avoid races with LocalStorage
    order_mode = _effective_order_mode()
    # Debug log writing removed to avoid creating local debug files.
    count_mode = st.session_state.get('count_mode', "10問")
    preset_map = {"10問": 10, "20問": 20, "30問": 30, "50問": 50}
    question_count = preset_map.get(count_mode, len(target_questions))

    # 出題プールを生成
    if order_mode == "おすすめ":
        user_name = st.session_state.get("user_name", "")
        quiz_questions, _ = _build_recommended_pool(target_questions, question_count, user_name)
    else:
        if order_mode == "シャッフル":
            pool = random.sample(target_questions, len(target_questions))
            quiz_questions = limit_questions(pool, question_count)
        elif order_mode == "順番通り（出題少ない順）":
            user_name = st.session_state.get("user_name", "")
            stats = get_question_stats(user_name)
            pool = sorted(
                target_questions,
                key=lambda q: stats.get(q.id, (0, 0, 0))[0],
            )
            quiz_questions = limit_questions(pool, question_count)
        else:
            pool = target_questions
            quiz_questions = limit_questions(pool, question_count)

    return quiz_questions


def render_quiz() -> None:
    import time as _time

    questions = st.session_state.quiz_questions
    index = st.session_state.current_index
    # If quiz_questions is empty (e.g. user started from calendar "今日の分"),
    # prepare questions according to current session settings and start the quiz.
    if not questions:
        try:
            all_questions = load_questions_from_db(DB_PATH)
            prepared = _prepare_quiz_questions(all_questions)
            # start_quiz will set session_state.quiz_questions, current_index, etc.
            start_quiz(prepared, st.session_state.get('show_japanese', False))
            questions = st.session_state.quiz_questions
            index = st.session_state.current_index
        except Exception:
            # If preparation fails, show an error and return to setup
            st.error("出題の準備に失敗しました。設定を確認してください。")
            st.session_state.stage = "setup"
            st.rerun()

    # ブラウザからの TTS 完了通知（クエリパラメータ tts_done を使用）を受け取り、
    # 現在の問題インデックスと一致すればカウントダウンを開始する。
    try:
        params = st.query_params
        if "tts_done" in params:
            try:
                tts_idx = int(params.get("tts_done")[0])
            except Exception:
                tts_idx = None
            if tts_idx is not None and tts_idx == index:
                # TTSからの通知は受け取るが、タイムアウト機能は廃止されたため
                # クエリをクリアしてループを避けるのみ行う。
                st.query_params.clear()
                st.rerun()
    except Exception:
        # experimental_get_query_params が制限されている場合があるが無視して進める
        pass

    if index >= len(questions):
        st.session_state.quiz_end_time = _time.time()
        # Quiz 終了時に一時的に設定した日付オーバーライドがあれば解除する
        # 学習時間を日次統計に追加
        try:
            user_name = st.session_state.get("user_name", "")
            start_time = st.session_state.get("quiz_start_time")
            end_time = st.session_state.get("quiz_end_time")
            if user_name and start_time and end_time and end_time >= start_time:
                seconds = int(end_time - start_time)
                # override_record_date が指定されている場合はそれを日付として使う
                add_daily_study_seconds(user_name, seconds)
                try:
                    # Record per-quiz session for fastest-time tracking
                    count = len(st.session_state.get("quiz_questions", []))
                    record_quiz_session(user_name, seconds, count)
                except Exception:
                    pass
        except Exception:
            pass
        st.session_state.stage = "result"
        st.rerun()

    q = questions[index]

    # タイムアウト機能は廃止され、サーバ/クライアント双方の時間切れ処理は削除されました。


    record_error = st.session_state.pop("record_error", "")
    if record_error:
        st.warning(record_error)

    # 出題画面ではページ上部の大きなタイトルを表示しない
    # (以前は st.title("English Quiz") がここにありましたが、UIをコンパクトにするため削除しています)

    # 画面上部にテーマ切替ボタンを表示
    render_theme_toggle()

    prog_col, abort_col = st.columns([5, 1])
    with prog_col:
        st.progress((index + 1) / len(questions), text=f"{index + 1} / {len(questions)}")
    with abort_col:
        if st.button("中断する", key="abort_quiz"):
            st.session_state.quiz_end_time = _time.time()
            # 中断時もオーバーライド解除フラグがセットされていれば解除
            # 学習時間を日次統計に追加
            try:
                user_name = st.session_state.get("user_name", "")
                start_time = st.session_state.get("quiz_start_time")
                end_time = st.session_state.get("quiz_end_time")
                if user_name and start_time and end_time and end_time >= start_time:
                    seconds = int(end_time - start_time)
                    add_daily_study_seconds(user_name, seconds)
            except Exception:
                pass
            st.session_state.stage = "result"
            st.rerun()

    # タイムアウト／カウントダウン機能は廃止されました。
    # 以前はクライアント側で残り時間を表示してページリロードでタイムアウト処理を促していましたが、
    # 現在はその処理を行いません。関連するセッションキー（question_timer_active 等）も削除されています。

    # デバッグ表示を削除しました（詳細なテーマ検出用のデバッグ情報を表示しない）
    st.subheader(f"Q{index + 1}")
    question_text = q.english or "(No English text)"
    st.markdown(
        (
            "<div class='quiz-question-text' style='white-space: pre-wrap;'>"
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

    # 🔊 読み上げボタン（Web Speech API - 括弧部分は効果音で置換）
    # （ ）や( )で文を分割し、間に効果音を挟む
    # 以前の正規表現は空の括弧にしかマッチせず意図通り動作しなかったため修正。
    # ここでは括弧文字で分割し、括弧内外のセグメントを順に得られるようにする。
    tts_parts = re.split(r'[（）()]', question_text)
    # 空文字や空白のみの要素を除去し、表示用に整形
    tts_parts = [p.strip() for p in tts_parts if p and p.strip()]
    tts_parts_js = [p.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'").replace("\n", " ") for p in tts_parts]
    parts_json = ",".join([f"'{p}'" for p in tts_parts_js])
    # シャッフル順の選択肢テキスト
    choices_js = []
    for dp, oi in enumerate(shuffle_order):
        c = choices[oi].replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'").replace("\n", " ")
        choices_js.append(f"'{dp + 1}. {c}'")
    choices_json = ",".join(choices_js)
    # 読み上げ回数の設定
    voice_repeat = st.session_state.get("voice_repeat", 2)
    max_rounds_js = voice_repeat
    voice_mode = st.session_state.get("voice_mode", False)
    auto_play_js = "true" if voice_mode and not st.session_state.answered else "false"
    if voice_mode:
        # ここにHTML/JSの正しい埋め込みを記述（省略）
        pass

    # --- 選択肢ボタンの表示（回答後も同じ並びで表示） ---
    for display_pos, original_idx in enumerate(shuffle_order):
        choice = choices[original_idx]
        label = f"{display_pos + 1}. {choice}"
        key = f"choice_{index}_{display_pos}"
        if not st.session_state.answered:
            if st.button(label, key=key):
                _answer_question(original_idx + 1)
                st.rerun()
        else:
            # 回答後はボタンではなく静的表示で同じ並びに保つ。
            # タイムアウト時は「グレーアウト」して選択できない状態に見せる。
            try:
                correct_original_idx = q.answer - 1
            except Exception:
                correct_original_idx = None
            is_selected = st.session_state.selected_index == (original_idx + 1)
            is_correct_choice = (correct_original_idx is not None and original_idx == correct_original_idx)
            safe_label = html.escape(label)
            # 共通ブロックスタイル（インラインで付与）
            q_block_base = "padding:10px;border-radius:6px;margin-bottom:8px;box-shadow:inset 0 -1px 0 rgba(0,0,0,0.05);"

            # 回答後の通常表示（選択・正解の強調）
            # 通常の回答後表示（選択・正解の強調）
            if _is_dark_mode():
                correct_bg = "#003300"
                correct_text = "#e5e7eb"
                selected_wrong_bg = "#331800"
                selected_wrong_text = "#e5e7eb"
                other_bg = "transparent"
                other_text = "#e5e7eb"
                q_border = "1px solid rgba(255,255,255,0.06)"
            else:
                correct_bg = "#e6f4ff"  # 薄い青
                correct_text = "#0b61c3"  # 青文字
                selected_wrong_bg = "#fdecec"  # 薄い赤
                selected_wrong_text = "#b91c1c"  # 赤文字
                other_bg = "transparent"
                other_text = "#000000"
                q_border = "none"

            if is_selected and is_correct_choice:
                style = f"background:{correct_bg};border:{q_border};color:{correct_text};{q_block_base}"
                st.markdown(f"<div style='{style}'><b>{safe_label}</b> ✅</div>", unsafe_allow_html=True)
            elif is_selected and not is_correct_choice:
                style = f"background:{selected_wrong_bg};border:{q_border};color:{selected_wrong_text};{q_block_base}"
                st.markdown(f"<div style='{style}'><b>{safe_label}</b></div>", unsafe_allow_html=True)
            elif is_correct_choice:
                style = f"background:{correct_bg};border:{q_border};color:{correct_text};{q_block_base}"
                st.markdown(f"<div style='{style}'><b>{safe_label}</b></div>", unsafe_allow_html=True)
            else:
                style = f"background:{other_bg};color:{other_text};{q_block_base}"
                st.markdown(f"<div style='{style}'>{safe_label}</div>", unsafe_allow_html=True)

    # 回答後の表示
    if st.session_state.answered:
        selected = st.session_state.selected_index
        # （報告ボタンは画面下部に統一して表示するため、ここでは表示しません）
        # 解説表示: detailed_explanations フォルダから該当ファイルを探して表示する
        try:
            explain_text = _load_explanation_for_question(q)
        except Exception:
            explain_text = None
        with st.expander("解説を表示"):
            if explain_text:
                # 改行を維持して表示
                # Markdownでは単一の改行は無視されるため、段落は二重改行で区切られ
                # 単一改行を明示的に Markdown のハードブレーク（行末に2つのスペース）に変換して保存します。
                try:
                    txt = explain_text.replace("\r\n", "\n").rstrip()
                    paras = txt.split("\n\n")
                    md_text = "\n\n".join(p.replace("\n", "  \n") for p in paras)
                    st.markdown(md_text, unsafe_allow_html=False)
                except Exception:
                    # フォールバック: 元のテキストをプレーンテキストで表示
                    st.text(explain_text)
            else:
                st.caption("解説ファイルが見つかりません。")
        # 正解・不正解表示（通常）
        if is_correct(q, selected):
            st.success("正解です！")
        else:
            correct_original_idx = q.answer - 1
            correct_display_pos = shuffle_order.index(correct_original_idx) + 1
            st.error(f"不正解です。正解は {correct_display_pos}. {choices[correct_original_idx]}")
        # 次の問題へ
        if st.button("次の問題へ", type="primary"):
            st.session_state.current_index += 1
            st.session_state.answered = False
            st.session_state.selected_index = None
            # クリア: 次の問題へ移動
            new_idx = st.session_state.current_index
            st.rerun()

    if st.session_state.show_japanese and q.japanese:
        st.caption(f"日本語: {q.japanese}")

    # --- タグ管理UI（画面一番下） ---
    user_question_tags = get_question_tags()
    user_tags = get_all_tags()
    default_tags = get_default_tags()
    default_question_tags = get_default_question_tags()
    qid = str(q.id)

    st.markdown("---")
    # タグ表示部分を折り畳み可能にする（常に折り畳んだ状態で表示）
    with st.expander("タグ（ハッシュタグ）", expanded=False):
        # ユーザータグ（1行目・編集可能）
        if user_tags:
            u_q_tags = user_question_tags.get(qid, [])
            tag_cols = st.columns(max(1, len(user_tags)))
            for i, tag in enumerate(user_tags):
                selected = tag in u_q_tags
                btn_label = f"✅ #{tag}" if selected else f"#{tag}"
                if tag_cols[i % len(tag_cols)].button(btn_label, key=f"tagbtn_{q.id}_{tag}"):
                    if selected:
                        new_tags = [t for t in u_q_tags if t != tag]
                    else:
                        new_tags = u_q_tags + [tag]
                    if new_tags:
                        user_question_tags[qid] = new_tags
                    else:
                        user_question_tags.pop(qid, None)
                    set_question_tags(user_question_tags)
                    try:
                        save_app_data(LS)
                    except Exception:
                        pass
                    st.rerun()

        # デフォルトタグ（2行目・読み取り専用）
        if default_tags:
            d_q_tags = default_question_tags.get(qid, [])
            dt_display = "　".join([f"✅ `#{t}`" if t in d_q_tags else f"`#{t}`" for t in default_tags])
            st.caption(f"📋 デフォルト: {dt_display}")

        if not user_tags and not default_tags:
            st.caption("タグはまだありません")

        # 新規ユーザータグ追加
        with st.form(f"add_tag_form_{q.id}", clear_on_submit=True):
            new_tag = st.text_input("新しいタグを追加", key=f"new_tag_input_{q.id}")
            submitted = st.form_submit_button("追加")
            if submitted and new_tag.strip():
                tag = new_tag.strip()
                updated = False
                combined = _get_combined_tags()
                if tag not in combined:
                    # update local list and persistent store
                    user_tags.append(tag)
                    set_all_tags(user_tags)
                    updated = True
                u_q_tags = user_question_tags.get(qid, [])
                if tag not in u_q_tags:
                    u_q_tags.append(tag)
                    user_question_tags[qid] = u_q_tags
                    set_question_tags(user_question_tags)
                    updated = True
                if updated:
                    # Persist to browser localStorage
                    try:
                        save_app_data(LS)
                    except Exception:
                        pass
                    # Mark that we've just added a tag so the rendering path can
                    # immediately prefer session-state-backed tag lists. This
                    # avoids race conditions where the LocalStorage component may
                    # asynchronously push older data back into the session.
                    st.session_state['_last_added_tag'] = tag
                    # Trigger a rerun to refresh the UI immediately
                    st.rerun()

    # 📧 この問題を報告（画面一番下）
    # 回答済みの場合に画面一番下へ報告リンクを一つだけ表示する
    if st.session_state.answered:
        user_name = st.session_state.get("user_name", "")
        import urllib.parse as _urlparse
        # qを直接参照
        choices = [q.choice1, q.choice2, q.choice3, q.choice4]
        # 報告メールの件名生成部分
        _report_subject = f"Quiz問題についての報告: Q{index + 1}"
        _report_lines = [
            f"問題番号: Q{index + 1}",
            f"問題文: {q.english or ''}",
            f"選択肢:",
            f"  1. {choices[0]}",
            f"  2. {choices[1]}",
            f"  3. {choices[2]}",
            f"  4. {choices[3]}",
            f"現在の正解: {q.answer}. {choices[q.answer - 1]}",
            "",
            "【問題点を記入してください】",
            "",
        ]
        _report_body = "\n".join(_report_lines)
        _to_addrs = ",".join(get_share_emails(user_name))
        # URLエンコードしてmailtoリンクを生成
        _mailto_url = f"mailto:{_urlparse.quote(_to_addrs)}?subject={_urlparse.quote(_report_subject)}&body={_urlparse.quote(_report_body)}"
        st.markdown(
            f'<a href="{_mailto_url}" onclick="window.location.href=this.href;return false;" style="display:inline-block;padding:0.4rem 1rem;background:{_theme_color("#ff9800", "#7c2d12")};color:{_theme_text_color("#ffffff", "#fff7ed")};border:1px solid {_theme_color("#ff9800", "#9a3412")};border-radius:8px;text-decoration:none;font-size:0.9rem;">📧 この問題を報告（メール）</a>',
            unsafe_allow_html=True,
        )

    _render_back_to_login_button()


# ─── メインルーティング ───────────────────────────────────────────────────────
def main() -> None:
    """ステージに応じて適切な画面をレンダリングする。"""
    init_state()

    # LocalStorage の非同期読み込みが完了したタイミングで再ロードが必要な場合は
    # ここで rerun を行い、確定データで画面を描画し直す。
    if st.session_state.get("_ls_data_tentative"):
        ensure_loaded(LS)
        if not st.session_state.get("_ls_data_tentative"):
            # 実データが取得できたので rerun して確定データで描画
            st.rerun()

    all_questions = load_questions()

    stage = st.session_state.get("stage", "login")

    if stage == "login":
        render_login()
    elif stage == "setup":
        render_setup(all_questions)
    elif stage == "quiz":
        render_quiz()
    elif stage == "result":
        render_result()
    elif stage == "history":
        render_history()
    elif stage == "tag_manage":
        render_tag_manage()
    else:
        render_login()


main()


