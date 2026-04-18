from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Literal

import pandas as pd

Mode = Literal["category", "all"]
CSV_ENCODINGS = ("utf-8-sig", "cp932", "shift_jis", "utf-8")


@dataclass(frozen=True)
class Question:
    id: int
    source_csv: str
    english: str
    choice1: str
    choice2: str
    choice3: str
    choice4: str
    answer: int
    japanese: str
    row_index: int


@dataclass(frozen=True)
class AnswerSummary:
    question_id: int
    category1: str
    category2: str
    english: str
    answered_date: str
    total_asked: int
    total_correct: int
    total_incorrect: int


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS imported_files (
                source_csv TEXT PRIMARY KEY,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Categoryカラムを除外したquestionsテーブル
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_csv TEXT NOT NULL,
                english TEXT NOT NULL,
                choice1 TEXT NOT NULL,
                choice2 TEXT NOT NULL,
                choice3 TEXT NOT NULL,
                choice4 TEXT NOT NULL,
                answer INTEGER NOT NULL,
                japanese TEXT NOT NULL,
                row_index INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # CSVから読み込んだデフォルトタグを保持するテーブル
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS default_tags (
                question_id INTEGER PRIMARY KEY,
                tag TEXT NOT NULL,
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
            """
        )
        # マイグレーション: row_index カラムが無ければ追加
        cols = [r[1] for r in conn.execute("PRAGMA table_info(questions)").fetchall()]
        if "row_index" not in cols:
            conn.execute("ALTER TABLE questions ADD COLUMN row_index INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS answer_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_name TEXT NOT NULL DEFAULT '',
                answered_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
                total_asked INTEGER NOT NULL,
                total_correct INTEGER NOT NULL,
                total_incorrect INTEGER NOT NULL,
                was_correct INTEGER NOT NULL CHECK (was_correct IN (0, 1)),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
            """
        )
        # マイグレーション: user_name カラムが無ければ追加
        ah_cols = [r[1] for r in conn.execute("PRAGMA table_info(answer_history)").fetchall()]
        if "user_name" not in ah_cols:
            conn.execute("ALTER TABLE answer_history ADD COLUMN user_name TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_answer_history_question_id
            ON answer_history(question_id)
            """
        )
        # 最後にログインしたユーザー名を保持するテーブル
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # 登録ユーザーテーブル
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_name TEXT PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def reset_db(db_path: Path) -> None:
    """Clear all imported question data while keeping schema intact."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM default_tags")
        conn.execute("DELETE FROM answer_history")
        conn.execute("DELETE FROM questions")
        conn.execute("DELETE FROM imported_files")
        conn.commit()


def reset_answer_history(db_path: Path, user_name: str | None = None) -> None:
    """Clear only answer history, keeping questions intact.

    If *user_name* is given, only that user's history is deleted.
    """
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        if user_name is not None:
            conn.execute("DELETE FROM answer_history WHERE user_name = ?", (user_name,))
        else:
            conn.execute("DELETE FROM answer_history")
        conn.commit()


def update_correct_index(db_path: Path, question_id: int, new_correct_index: int) -> None:
    """Update the correct answer index for a question."""
    if new_correct_index < 1 or new_correct_index > 4:
        raise ValueError(f"correct_index must be 1-4, got {new_correct_index}")
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE questions SET correct_index = ? WHERE id = ?",
            (new_correct_index, question_id),
        )
        conn.commit()


def export_correct_answers_to_csvs(input_dir: Path, db_path: Path) -> int:
    """Write back current correct_index values from DB into the source CSV files.

    Uses row_index (0-based CSV row number) to identify rows precisely.
    Returns the number of CSV files updated.
    """
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source_csv, row_index, correct_index FROM questions ORDER BY source_csv, row_index"
        ).fetchall()

    # source_csv → {row_index: correct_index}
    updates_by_csv: dict[str, dict[int, int]] = {}
    for source_csv, row_index, correct_index in rows:
        updates_by_csv.setdefault(source_csv, {})[int(row_index)] = int(correct_index)

    updated_count = 0
    for source_csv, row_map in updates_by_csv.items():
        csv_path = input_dir / source_csv
        if not csv_path.exists():
            continue

        # 読み込み時のエンコーディングを検出
        df: pd.DataFrame | None = None
        used_encoding: str = "utf-8-sig"
        for encoding in CSV_ENCODINGS:
            try:
                df = pd.read_csv(csv_path, encoding=encoding)
                used_encoding = encoding
                break
            except UnicodeDecodeError:
                continue

        if df is None or "Answer" not in df.columns:
            continue

        changed = False
        for row_idx, new_answer in row_map.items():
            if row_idx < 0 or row_idx >= len(df):
                continue
            current_answer = df.iloc[row_idx]["Answer"]
            try:
                if int(current_answer) != new_answer:
                    df.at[df.index[row_idx], "Answer"] = new_answer
                    changed = True
            except (TypeError, ValueError):
                df.at[df.index[row_idx], "Answer"] = new_answer
                changed = True

        if changed:
            df.to_csv(csv_path, index=False, encoding=used_encoding)
            updated_count += 1

    return updated_count


def sync_csvs_to_db(input_dir: Path, db_path: Path) -> int:
    """Import all CSV files under input_dir once, keyed by CSV file name."""
    init_db(db_path)
    csv_paths = sorted(input_dir.glob("*.csv"))
    imported_file_count = 0

    with sqlite3.connect(db_path) as conn:
        imported_files = {
            row[0]
            for row in conn.execute("SELECT source_csv FROM imported_files").fetchall()
        }

        for csv_path in csv_paths:
            source_csv = csv_path.name
            if source_csv in imported_files:
                continue

            df = read_quiz_csv(csv_path)
            questions, default_tags = normalize_questions(df)

            conn.executemany(
                """
                INSERT INTO questions (
                    source_csv, english, choice1, choice2, choice3, choice4, answer, japanese, row_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source_csv,
                        q.english,
                        q.choice1,
                        q.choice2,
                        q.choice3,
                        q.choice4,
                        q.answer,
                        q.japanese,
                        q.row_index,
                    )
                    for q in questions
                ],
            )
            # 挿入した問題のIDを取得してデフォルトタグを保存
            last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            first_id = last_id - len(questions) + 1
            for i, tag in enumerate(default_tags):
                if tag:
                    conn.execute(
                        "INSERT INTO default_tags (question_id, tag) VALUES (?, ?)",
                        (first_id + i, tag),
                    )
            conn.execute("INSERT INTO imported_files (source_csv) VALUES (?)", (source_csv,))
            imported_files.add(source_csv)
            imported_file_count += 1

        conn.commit()

    return imported_file_count


def reload_db_from_csvs(input_dir: Path, db_path: Path) -> int:
    """Rebuild question data from all CSV files under input_dir."""
    reset_db(db_path)
    return sync_csvs_to_db(input_dir, db_path)


def load_default_tags(db_path: Path) -> dict[int, str]:
    """Return {question_id: tag} for all questions with a default tag from CSV."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT question_id, tag FROM default_tags").fetchall()
    return {int(row[0]): row[1] for row in rows}


def load_questions_from_db(db_path: Path) -> list[Question]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, source_csv, english, choice1, choice2, choice3, choice4, answer, japanese, row_index
            FROM questions
            ORDER BY source_csv, row_index
            """
        ).fetchall()

    return [
        Question(
            id=int(row[0]),
            source_csv=row[1],
            english=row[2],
            choice1=row[3],
            choice2=row[4],
            choice3=row[5],
            choice4=row[6],
            answer=int(row[7]),
            japanese=row[8],
            row_index=int(row[9]),
        )
        for row in rows
    ]


def record_answer_history(db_path: Path, question_id: int, is_correct_answer: bool, user_name: str = "") -> None:
    """Insert one answer log row with cumulative totals for the question (per user)."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        latest = conn.execute(
            """
            SELECT total_asked, total_correct, total_incorrect
            FROM answer_history
            WHERE question_id = ? AND user_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (question_id, user_name),
        ).fetchone()

        asked = int(latest[0]) if latest else 0
        correct = int(latest[1]) if latest else 0
        incorrect = int(latest[2]) if latest else 0

        asked += 1
        if is_correct_answer:
            correct += 1
        else:
            incorrect += 1

        conn.execute(
            """
            INSERT INTO answer_history (
                question_id, user_name, answered_date, total_asked, total_correct, total_incorrect, was_correct
            ) VALUES (?, ?, date('now', 'localtime'), ?, ?, ?, ?)
            """,
            (question_id, user_name, asked, correct, incorrect, 1 if is_correct_answer else 0),
        )
        conn.commit()


def load_answer_summaries(db_path: Path, user_name: str = "") -> list[AnswerSummary]:
    """Return latest cumulative answer totals per answered question for a specific user."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT q.id, '', '', q.english,
                   ah.answered_date, ah.total_asked, ah.total_correct, ah.total_incorrect
            FROM answer_history ah
            INNER JOIN (
                SELECT question_id, MAX(id) AS latest_id
                FROM answer_history
                WHERE user_name = ?
                GROUP BY question_id
            ) latest ON latest.latest_id = ah.id
            INNER JOIN questions q ON q.id = ah.question_id
            ORDER BY ah.answered_date DESC, ah.total_asked DESC, q.id ASC
            """,
            (user_name,),
        ).fetchall()

    return [
        AnswerSummary(
            question_id=int(row[0]),
            category1=row[1],  # 空文字
            category2=row[2],  # 空文字
            english=row[3],
            answered_date=row[4],
            total_asked=int(row[5]),
            total_correct=int(row[6]),
            total_incorrect=int(row[7]),
        )
        for row in rows
    ]


def load_question_stats(db_path: Path, user_name: str = "") -> dict[int, tuple[int, int, int]]:
    """Return latest cumulative stats per question as {question_id: (total_asked, total_correct, total_incorrect)} for a specific user."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ah.question_id, ah.total_asked, ah.total_correct, ah.total_incorrect
            FROM answer_history ah
            INNER JOIN (
                SELECT question_id, MAX(id) AS latest_id
                FROM answer_history
                WHERE user_name = ?
                GROUP BY question_id
            ) latest ON latest.latest_id = ah.id
            """,
            (user_name,),
        ).fetchall()
    return {int(row[0]): (int(row[1]), int(row[2]), int(row[3])) for row in rows}


def read_quiz_csv(csv_path: Path) -> pd.DataFrame:
    """Read CSV with a safe encoding fallback for Japanese datasets."""
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(csv_path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Failed to read CSV with supported encodings: {csv_path}") from last_error


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_questions(df: pd.DataFrame) -> tuple[list[Question], list[str]]:
    """CSVからQuestion一覧とDefaultTagリストを返す。

    Returns: (questions, default_tags)  ※ default_tags[i] は questions[i] に対応
    """
    required_columns = {"English", "1", "2", "3", "4", "Answer", "Japanese"}
    missing = required_columns - set(df.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"CSV is missing required columns: {missing_text}")

    has_default_tag = "DefaultTag" in df.columns

    questions: list[Question] = []
    default_tags: list[str] = []
    for idx, row in df.iterrows():
        try:
            idx_int = int(idx)
        except Exception:
            idx_int = 0
        try:
            answer = int(row["Answer"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Answer に数値でない行があります") from exc
        if answer < 1 or answer > 4:
            raise ValueError(f"Answer は 1-4 である必要があります: Answer={answer}")
        questions.append(
            Question(
                id=0,
                source_csv="",
                english=_clean_text(row["English"]),
                choice1=_clean_text(row["1"]),
                choice2=_clean_text(row["2"]),
                choice3=_clean_text(row["3"]),
                choice4=_clean_text(row["4"]),
                answer=answer,
                japanese=_clean_text(row["Japanese"]),
                row_index=idx_int,
            )
        )
        dt_raw = _clean_text(row["DefaultTag"]) if has_default_tag else ""
        default_tags.append("" if not dt_raw or dt_raw.lower() == "none" else dt_raw)
    return questions, default_tags


def get_category_options(questions: list[Question]) -> tuple[list[str], list[str]]:
    # カテゴリ機能廃止のため空リスト返却
    return [], []


def _normalize_selection(selected: str | list[str] | tuple[str, ...] | set[str] | None) -> set[str] | None:
    if selected is None:
        return None
    if isinstance(selected, str):
        text = selected.strip()
        return {text} if text else None
    normalized = {item.strip() for item in selected if item and item.strip()}
    return normalized or None


def filter_questions(
    questions: list[Question],
    mode: Mode,
    selected_category: str | list[str] | tuple[str, ...] | set[str] | None = None,
    _unused: str | list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[Question]:
    category_set = _normalize_selection(selected_category)
    if mode == "all" and not category_set:
        return questions
    return [q for q in questions if not category_set or q.category in category_set]


def is_correct(question: Question, selected_index: int) -> bool:
    return question.answer == selected_index


def limit_questions(questions: list[Question], count: int) -> list[Question]:
    if count <= 0:
        return []
    return questions[:count]

def save_last_user(db_path: Path, user_name: str) -> None:
    """Save the last logged-in user name to the DB."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('last_user', ?)",
            (user_name,),
        )
        conn.commit()


def load_last_user(db_path: Path) -> str:
    """Load the last logged-in user name from the DB. Returns '' if not set."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'last_user'"
        ).fetchone()
    return row[0] if row else ""


def get_all_users(db_path: Path) -> list[str]:
    """Return a list of all distinct user names that have answer history."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_name FROM answer_history WHERE user_name != '' ORDER BY user_name"
        ).fetchall()
    return [row[0] for row in rows]


def register_user(db_path: Path, user_name: str) -> None:
    """Register a new user."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (user_name) VALUES (?)",
            (user_name,),
        )
        conn.commit()


def get_registered_users(db_path: Path) -> list[dict[str, str]]:
    """Return all registered users as a list of dicts with 'user_name'."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT user_name FROM users ORDER BY user_name"
        ).fetchall()
    return [{"user_name": row[0]} for row in rows]


def user_exists(db_path: Path, user_name: str) -> bool:
    """Check if a user name is already registered."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE user_name = ?", (user_name,)
        ).fetchone()
    return row is not None

