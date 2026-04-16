from pathlib import Path
import argparse
import sys
from quiz_logic import reload_db_from_csvs, load_questions_from_db

def initialize_db_from_initial_csv(input_dir: Path, db_path: Path) -> tuple[int, int]:
    """
    initial.csv からDBを初期化する。
    Returns: (imported_count, question_count)
    """
    imported_count = reload_db_from_csvs(input_dir, db_path)
    reloaded_questions = load_questions_from_db(db_path)
    return imported_count, len(reloaded_questions)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="initial.csv からDBを初期化します")
    parser.add_argument(
        "--input_dir",
        type=str,
        default=str(Path(__file__).parent / "input"),
        help="CSVファイルのディレクトリ (デフォルト: ./input)"
    )
    parser.add_argument(
        "--db_path",
        type=str,
        default=str(Path(__file__).parent / "quiz.db"),
        help="初期化するDBファイルパス (デフォルト: ./quiz.db)"
    )
    args = parser.parse_args()
    input_dir = Path(args.input_dir)
    db_path = Path(args.db_path)
    try:
        imported_count, question_count = initialize_db_from_initial_csv(input_dir, db_path)
        print(f"DBをinitial.csvから再構築しました（取込CSV: {imported_count}件 / 問題数: {question_count}件）")
    except Exception as exc:
        print(f"initial.csvからのDB再構築に失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)
