from pathlib import Path
import sqlite3

from quiz_logic import (
    filter_questions,
    is_correct,
    limit_questions,
    load_answer_summaries,
    load_questions_from_db,
    record_answer_history,
    reload_db_from_csvs,
    sync_csvs_to_db,
)


def test_sync_and_load_questions_from_db(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"

    imported = sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    assert imported >= 1
    assert len(questions) > 0
    assert all(1 <= q.answer <= 4 for q in questions)


def test_skip_reimport_for_same_csv_name(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"

    sync_csvs_to_db(input_dir, db_path)
    questions_first = load_questions_from_db(db_path)

    imported_again = sync_csvs_to_db(input_dir, db_path)
    questions_second = load_questions_from_db(db_path)

    assert imported_again == 0
    assert len(questions_first) == len(questions_second)


def test_reload_db_from_csvs_rebuilds_questions(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"

    sync_csvs_to_db(input_dir, db_path)
    questions_before = load_questions_from_db(db_path)

    imported = reload_db_from_csvs(input_dir, db_path)
    questions_after = load_questions_from_db(db_path)

    assert imported >= 1
    assert len(questions_before) > 0
    assert len(questions_after) == len(questions_before)


def test_filter_questions_by_category(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    target = questions[0]
    filtered = filter_questions(questions, "category", target.category)

    assert len(filtered) > 0
    assert all(q.category == target.category for q in filtered)


def test_filter_questions_by_multiple_categories(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    category_values = sorted({q.category for q in questions if q.category})
    selected_category = category_values[:2]

    filtered = filter_questions(questions, "category", selected_category)

    assert len(filtered) > 0
    assert all(q.category in set(selected_category) for q in filtered)


def test_filter_questions_all_mode_respects_selected_categories_and_order(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    target = questions[0]
    selected_category = [target.category]
    expected = [q for q in questions if q.category in set(selected_category)]

    filtered = filter_questions(questions, "all", selected_category)

    assert filtered == expected


def test_is_correct(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    q = questions[0]
    assert is_correct(q, q.answer)
    wrong = 1 if q.answer != 1 else 2
    assert not is_correct(q, wrong)


def test_limit_questions(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    limited = limit_questions(questions, 10)
    assert len(limited) == min(10, len(questions))
    assert limited == questions[: len(limited)]


def test_record_answer_history_accumulates_per_question(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    question = questions[0]
    record_answer_history(db_path, question.id, True)
    record_answer_history(db_path, question.id, False)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT question_id, answered_date, total_asked, total_correct, total_incorrect, was_correct
            FROM answer_history
            WHERE question_id = ?
            ORDER BY id
            """,
            (question.id,),
        ).fetchall()

    assert len(rows) == 2
    assert rows[0][0] == question.id
    assert rows[0][1]
    assert rows[0][2:] == (1, 1, 0, 1)
    assert rows[1][0] == question.id
    assert rows[1][1]
    assert rows[1][2:] == (2, 1, 1, 0)


def test_load_answer_summaries_returns_latest_totals(tmp_path: Path) -> None:
    input_dir = Path(__file__).resolve().parents[1] / "input"
    db_path = tmp_path / "quiz.db"
    sync_csvs_to_db(input_dir, db_path)
    questions = load_questions_from_db(db_path)

    question = questions[0]
    record_answer_history(db_path, question.id, True)
    record_answer_history(db_path, question.id, False)

    summaries = load_answer_summaries(db_path)
    target = next(item for item in summaries if item.question_id == question.id)

    assert target.total_asked == 2
    assert target.total_correct == 1
    assert target.total_incorrect == 1

