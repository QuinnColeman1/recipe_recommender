"""End-to-end: CSV -> data_processor -> build_app_db -> recommender."""

import csv
import json

import duckdb
import pytest

from data.build_app_db import build_app_db
from data.data_processor import process_csv
from recipe_app.main import EnhancedRecipeRecommender, MealType, SearchFilters

ROWS = [
    (
        "Chocolate Chip Cookies",
        ["2 c. flour", "1 c. sugar", "1 c. chocolate chips", "2 eggs"],
        ["flour", "sugar", "chocolate chips", "eggs"],
        ["Mix.", "Bake at 375 for 10 minutes."],
    ),
    (
        "Swiss Steak",
        ["1 1/2 lb. round steak", "1 can tomatoes", "1 onion"],
        ["tomatoes", "onion"],
        ["Brown steak 10 minutes.", "Add tomatoes and simmer 1 1/2 hours. Serves 4."],
    ),
    # exact duplicate of the first recipe -> removed
    (
        "Chocolate Chip Cookies",
        ["2 c. flour", "1 c. sugar", "1 c. chocolate chips", "2 eggs"],
        ["flour", "sugar", "chocolate chips", "eggs"],
        ["Mix.", "Bake at 375 for 10 minutes."],
    ),
    ("Empty", [], [], []),  # no ingredients/directions -> removed
]


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "recipes.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["", "title", "ingredients", "directions", "link", "source", "NER"]
        )
        for i, (title, ings, ner, steps) in enumerate(ROWS):
            writer.writerow(
                [
                    i,
                    title,
                    json.dumps(ings),
                    json.dumps(steps),
                    f"www.example.com/{i}",
                    "Gathered",
                    json.dumps(ner),
                ]
            )
    return path


def test_pipeline(csv_path, tmp_path):
    db = tmp_path / "clean.db"
    stats = process_csv(csv_path, db, workers=1)
    assert stats["rows_read"] == 4
    assert stats["total_recipes"] == 2

    con = duckdb.connect(str(db), read_only=True)
    steak = con.execute(
        "SELECT recipe_id, is_vegetarian, total_time, servings, meal_type, ingredients_clean, source "
        "FROM recipes WHERE title = 'Swiss Steak'"
    ).fetchone()
    con.close()
    assert steak[0] == 1  # ids come from the CSV's index column
    assert steak[1] is False  # round steak recovered although NER missed it
    # 100 min in the directions + estimated prep (5 + 3 ingredients)
    assert steak[2] == 108 and steak[3] == 4
    assert steak[4] == "dinner"
    assert not list(tmp_path.glob("*.staging.db"))
    assert "round steak" in steak[5]
    assert steak[6] == "Gathered"

    app_db = tmp_path / "app.db"
    build_app_db(db, app_db)
    rec = EnhancedRecipeRecommender(app_db)
    results = rec.search_by_ingredients(["eggs", "chocolate"])
    assert [r["title"] for r in results] == ["Chocolate Chip Cookies"]
    assert results[0]["link"] == "https://www.example.com/0"
    assert results[0]["ingredient_quantities"][0] == "2 c."
    dessert = rec.browse_recipes(SearchFilters(meal_type=MealType.DESSERT))
    assert [r["title"] for r in dessert] == ["Chocolate Chip Cookies"]
    rec.close()


def test_refuses_to_overwrite(csv_path, tmp_path):
    db = tmp_path / "clean.db"
    db.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        process_csv(csv_path, db, workers=1)
    assert db.read_bytes() == b"keep me"


# ------------------------------------------------------------ more processor


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_plain_text_csv_without_ner_or_id(tmp_path):
    """Other datasets: one ingredient per line, no NER column, no index column."""
    csv_path = write_csv(
        tmp_path / "plain.csv",
        ["title", "ingredients", "directions"],
        [
            [
                "Garlic Bread",
                "1 loaf French bread\n1/2 c. butter\n2 cloves garlic",
                "Spread.\nBake 10 minutes.",
            ],
            ["Lemonade", "1 c. lemon juice\n1 c. sugar\n6 c. water", "Stir well."],
        ],
    )
    db = tmp_path / "plain.db"
    process_csv(csv_path, db, workers=1)
    con = duckdb.connect(str(db), read_only=True)
    rows = dict(
        (title, (rid, ings, meal))
        for rid, title, ings, meal in con.execute(
            "SELECT recipe_id, title, ingredients_clean, meal_type FROM recipes"
        ).fetchall()
    )
    con.close()
    assert sorted(r[0] for r in rows.values()) == [0, 1]  # row numbers as ids
    assert rows["Garlic Bread"][1] == ["french bread", "butter", "garlic"]
    assert rows["Lemonade"][2] == "drink"


def test_limit_overwrite_and_multiple_workers(csv_path, tmp_path):
    db = tmp_path / "clean.db"
    stats = process_csv(csv_path, db, limit=2, workers=2, batch_size=1)
    assert stats["rows_read"] == 2 and stats["total_recipes"] == 2

    stats = process_csv(csv_path, db, workers=2, overwrite=True)
    assert stats["rows_read"] == 4 and stats["total_recipes"] == 2
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".db") == [
        "clean.db"
    ]


def test_missing_csv(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_csv(tmp_path / "nope.csv", tmp_path / "out.db")


def test_missing_required_columns(tmp_path):
    csv_path = write_csv(tmp_path / "bad.csv", ["title", "ingredients"], [["A", "[]"]])
    with pytest.raises(ValueError, match="directions"):
        process_csv(csv_path, tmp_path / "out.db", workers=1)
    assert not (tmp_path / "out.db").exists()


def test_empty_csv_leaves_no_files(tmp_path):
    csv_path = write_csv(
        tmp_path / "empty.csv", ["title", "ingredients", "directions"], []
    )
    with pytest.raises(ValueError, match="No rows"):
        process_csv(csv_path, tmp_path / "out.db", workers=1)
    assert [p.name for p in tmp_path.iterdir()] == ["empty.csv"]


def test_bad_row_is_skipped(monkeypatch):
    import data.data_processor as dp

    real = dp.process_record

    def flaky(row):
        if row["title"] == "boom":
            raise RuntimeError("bad row")
        return real(row)

    monkeypatch.setattr(dp, "process_record", flaky)
    rows = [
        {"recipe_id": 1, "title": "boom", "ingredients": "[]", "directions": "[]"},
        {
            "recipe_id": 2,
            "title": "Toast",
            "ingredients": '["1 slice bread"]',
            "directions": '["Toast."]',
        },
    ]
    out = dp._process_chunk(rows)
    assert [r["recipe_id"] for r in out] == [2]


def test_processor_cli(csv_path, tmp_path, monkeypatch, capsys):
    import data.data_processor as dp

    db = tmp_path / "cli.db"
    monkeypatch.setattr(
        "sys.argv",
        [
            "data_processor",
            "--csv-path",
            str(csv_path),
            "--db-path",
            str(db),
            "--workers",
            "1",
        ],
    )
    dp.main()
    out = capsys.readouterr().out
    assert "kept 2 recipes" in out
    assert "Meal types:" in out
    assert f"build_app_db --source {db}" in out


# ------------------------------------------------------------ build_app_db


def test_build_app_db_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_app_db(tmp_path / "nope.db", tmp_path / "app.db")


def test_build_app_db_replaces_stale_build_and_old_output(csv_path, tmp_path):
    db = tmp_path / "clean.db"
    process_csv(csv_path, db, workers=1)
    app_db = tmp_path / "app.db"
    (tmp_path / "app.building.db").write_bytes(b"left over from a crash")
    app_db.write_bytes(b"old")

    build_app_db(db, app_db)
    assert not (tmp_path / "app.building.db").exists()
    con = duckdb.connect(str(app_db), read_only=True)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    vocab = {r[0] for r in con.execute("SELECT name FROM ingredient_vocab").fetchall()}
    con.close()
    assert tables == {"recipes", "ingredient_vocab", "recipe_ingredients"}
    assert {"round steak", "chocolate chips", "eggs"} <= vocab


def test_build_app_db_cli(csv_path, tmp_path, monkeypatch, capsys):
    import data.build_app_db as bad

    db = tmp_path / "clean.db"
    process_csv(csv_path, db, workers=1)
    monkeypatch.setattr(
        "sys.argv",
        ["build_app_db", "--source", str(db), "--output", str(tmp_path / "app.db")],
    )
    bad.main()
    assert "Done in" in capsys.readouterr().out
    assert (tmp_path / "app.db").exists()
