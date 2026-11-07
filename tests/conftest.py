"""Test fixtures: a tiny database built the same way as the real app database."""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.build_app_db import build_app_db  # noqa: E402
from recipe_app.main import EnhancedRecipeRecommender, SearchFilters  # noqa: E402

# Same columns/types as the `recipes` table data_processor.py writes, including
# one column the app doesn't use (to check the lean build drops it).
SOURCE_SCHEMA = """
    CREATE TABLE recipes (
        recipe_id INTEGER, title VARCHAR, ingredients VARCHAR, directions VARCHAR,
        prep_time INTEGER, cook_time INTEGER, total_time INTEGER, servings INTEGER,
        difficulty_level VARCHAR, meal_type VARCHAR,
        ingredients_clean VARCHAR[], ingredients_original VARCHAR[],
        ingredient_categories VARCHAR[], ingredient_count INTEGER,
        is_vegetarian BOOLEAN, is_vegan BOOLEAN, is_gluten_free BOOLEAN,
        is_dairy_free BOOLEAN, is_nut_free BOOLEAN, is_low_carb BOOLEAN,
        is_dessert BOOLEAN, is_high_protein BOOLEAN, is_low_fat BOOLEAN,
        is_high_fiber BOOLEAN, recipe_completeness_score FLOAT, search_text VARCHAR,
        ingredient_quantities VARCHAR[], link VARCHAR, source VARCHAR
    )
"""

# (id, title, ingredients, categories, total_time, difficulty, meal_type,
#  vegetarian, vegan, gluten_free, nut_free, quality)
RECIPES = [
    (
        1,
        "Pasta with Tomato Sauce",
        ["pasta", "tomato sauce", "basil"],
        ["grain", "vegetable", "herbs_spices"],
        20,
        "easy",
        "dinner",
        True,
        True,
        False,
        True,
        0.95,
    ),
    (
        2,
        "Vegetable Stir Fry",
        ["rice", "mixed vegetables", "soy sauce"],
        ["grain", "vegetable", "other"],
        30,
        "medium",
        "lunch",
        True,
        True,
        False,
        True,
        0.9,
    ),
    (
        3,
        "Chicken Fried Rice",
        ["chicken breast", "rice", "egg", "soy sauce"],
        ["protein", "grain", "protein", "other"],
        None,
        "medium",
        "dinner",
        False,
        False,
        False,
        True,
        0.85,
    ),
    (
        4,
        "Peanut Butter Cookies",
        ["peanut butter", "confectioner's sugar", "egg"],
        ["protein", "sweetener", "protein"],
        25,
        "easy",
        "dessert",
        True,
        False,
        True,
        False,
        0.8,
    ),
    (
        5,
        "Slow Roast Chicken",
        ["whole chicken", "garlic", "lemon"],
        ["protein", "vegetable", "fruit"],
        180,
        "hard",
        "dinner",
        False,
        False,
        True,
        True,
        0.6,
    ),
]


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db")
    source, app_db = tmp / "source.db", tmp / "app.db"

    con = duckdb.connect(str(source))
    con.execute(SOURCE_SCHEMA)
    for (
        rid,
        title,
        ings,
        cats,
        total,
        diff,
        meal,
        veg,
        vegan,
        gf,
        nut_free,
        quality,
    ) in RECIPES:
        con.execute(
            "INSERT INTO recipes VALUES (?, ?, ?, ?, NULL, NULL, ?, 2, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, FALSE, ?, FALSE, ?, FALSE, FALSE, FALSE, ?, ?, ?, ?, 'test')",
            [
                rid,
                title,
                ", ".join(ings),
                "Cook it.",
                total,
                diff,
                meal,
                ings,
                ings,
                cats,
                len(ings),
                veg,
                vegan,
                gf,
                nut_free,
                meal == "dessert",
                quality,
                f"{title.lower()} {' '.join(ings)}",
                ["1"] * len(ings),
                f"https://example.com/{rid}",
            ],
        )
    con.close()

    build_app_db(source, app_db)
    return str(app_db)


@pytest.fixture
def recipe_recommender(test_db_path):
    rec = EnhancedRecipeRecommender(test_db_path)
    yield rec
    rec.close()


@pytest.fixture
def search_filters():
    return SearchFilters()
