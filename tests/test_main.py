"""Tests for recipe_app.main (search logic)."""

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from recipe_app.main import (
    DifficultyLevel,
    EnhancedRecipeRecommender,
    MealType,
    SearchFilters,
    SortBy,
    _singular,
    min_matches_needed,
)


def ids(results):
    return [r["recipe_id"] for r in results]


def test_initialization(recipe_recommender):
    assert recipe_recommender.is_connected is True
    assert recipe_recommender.connection_error is None


def test_missing_database_reports_error(tmp_path):
    rec = EnhancedRecipeRecommender(tmp_path / "nope.db")
    assert rec.is_connected is False
    assert "not found" in rec.connection_error
    assert rec.search_by_text("pasta") == []


def test_database_without_lookup_tables_is_rejected(tmp_path):
    path = tmp_path / "old.db"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE recipes (recipe_id INTEGER)")
    con.close()
    rec = EnhancedRecipeRecommender(path)
    assert rec.is_connected is False
    assert "build_app_db" in rec.connection_error


def test_lean_build_drops_unused_columns(test_db_path):
    con = duckdb.connect(test_db_path, read_only=True)
    cols = {r[0] for r in con.execute("DESCRIBE recipes").fetchall()}
    con.close()
    assert "ingredients" not in cols
    assert "search_text" in cols


def test_get_database_stats(recipe_recommender):
    stats = recipe_recommender.get_database_stats()
    assert stats["total_recipes"] == 5
    assert stats["vegan_count"] == 2
    # Average over recipes with a time (20, 30, 25, 180), not the quality score
    assert stats["avg_time"] == 64


def test_search_by_ingredients_requires_all(recipe_recommender, search_filters):
    results = recipe_recommender.search_by_ingredients(["rice", "soy"], search_filters)
    assert sorted(ids(results)) == [2, 3]
    assert all(r["match_percentage"] == 100 for r in results)


def test_search_by_ingredients_substring_and_case(recipe_recommender):
    assert ids(recipe_recommender.search_by_ingredients(["  CHICKEN "])) in (
        [3, 5],
        [5, 3],
    )


def test_search_by_ingredients_apostrophe(recipe_recommender):
    assert ids(recipe_recommender.search_by_ingredients(["confectioner's sugar"])) == [
        4
    ]


def test_search_by_ingredients_sql_is_not_injectable(recipe_recommender):
    assert recipe_recommender.search_by_ingredients(["%' OR 1=1 --"]) == []


def test_search_by_ingredients_exclude(recipe_recommender):
    filters = SearchFilters(exclude_ingredients=["peanut"])
    assert ids(recipe_recommender.search_by_ingredients(["egg"], filters)) == [3]


def test_search_by_ingredients_filters(recipe_recommender):
    filters = SearchFilters(is_vegan=True, meal_type=MealType.LUNCH)
    assert ids(recipe_recommender.search_by_ingredients(["sauce"], filters)) == [2]


def test_search_by_ingredients_sort_by_time(recipe_recommender):
    results = recipe_recommender.search_by_ingredients(["chicken"], sort_by=SortBy.TIME)
    assert ids(results) == [5, 3]  # unknown time sorts last


def test_search_by_ingredients_empty(recipe_recommender):
    assert recipe_recommender.search_by_ingredients(["", "  "]) == []


def test_search_by_text(recipe_recommender, search_filters):
    results = recipe_recommender.search_by_text("pasta", search_filters)
    assert ids(results) == [1]
    assert results[0]["quality_score"] > 0.9


def test_search_by_text_applies_filters(recipe_recommender):
    filters = SearchFilters(is_gluten_free=True)
    assert ids(recipe_recommender.search_by_text("chicken", filters)) == [5]


def test_search_by_text_title_matches_first(recipe_recommender):
    # "rice" is in recipe 3's title and recipe 2's ingredients
    assert ids(recipe_recommender.search_by_text("rice"))[0] == 3


def test_get_recipe_by_id(recipe_recommender):
    recipe = recipe_recommender.get_recipe_by_id(1)
    assert recipe["title"] == "Pasta with Tomato Sauce"
    assert recipe_recommender.get_recipe_by_id(999) is None


def test_browse_recipes(recipe_recommender, search_filters):
    assert len(recipe_recommender.browse_recipes(search_filters)) == 5

    filters = SearchFilters(
        meal_type=MealType.DINNER, difficulty_level=DifficultyLevel.EASY
    )
    assert ids(recipe_recommender.browse_recipes(filters)) == [1]


def test_browse_recipes_dietary_filter(recipe_recommender):
    results = recipe_recommender.browse_recipes(SearchFilters(is_vegan=True))
    assert sorted(ids(results)) == [1, 2]


def test_browse_recipes_sort_and_quality(recipe_recommender):
    results = recipe_recommender.browse_recipes(
        SearchFilters(min_quality_score=0.8), sort_by=SortBy.INGREDIENTS
    )
    assert 5 not in ids(results)
    counts = [r["ingredient_count"] for r in results]
    assert counts == sorted(counts)


def test_get_quick_recipes(recipe_recommender):
    results = recipe_recommender.get_quick_recipes(max_time=25, limit=5)
    assert ids(results) == [1, 4]
    assert all(r["total_time"] <= 25 for r in results)


def test_get_quick_recipes_does_not_mutate_filters(recipe_recommender):
    filters = SearchFilters(is_vegan=True)
    assert ids(recipe_recommender.get_quick_recipes(60, 5, filters)) == [1, 2]
    assert filters.max_total_time is None


def test_search_by_ingredients_plural_input(recipe_recommender):
    # "tomatoes" should still find "tomato sauce"
    assert ids(recipe_recommender.search_by_ingredients(["Tomatoes"])) == [1]
    assert ids(recipe_recommender.search_by_ingredients(["eggs"])) in ([3, 4], [4, 3])


def test_results_include_link_source_and_quantities(recipe_recommender):
    recipe = recipe_recommender.search_by_text("pasta")[0]
    assert recipe["link"] == "https://example.com/1"
    assert recipe["source"] == "test"
    assert recipe["ingredient_quantities"] == ["1", "1", "1"]


def test_title_matches_rank_first(recipe_recommender):
    # Both contain chicken; neither has it more prominently in the list, but
    # only the title decides here: recipe 3 "Chicken Fried Rice" vs 5 "Slow Roast Chicken"
    results = recipe_recommender.search_by_ingredients(["rice"])
    assert ids(results)[0] == 3  # "Chicken Fried Rice" has rice in its title


# ------------------------------------------------------------ more search


@pytest.mark.parametrize(
    "word, single",
    [
        ("tomatoes", "tomato"),
        ("berries", "berry"),
        ("peaches", "peach"),
        ("eggs", "egg"),
        ("glass", "glass"),
        ("rice", "rice"),
        ("gas", "gas"),
    ],
)
def test_singular(word, single):
    assert _singular(word) == single


def test_recipe_db_environment_variable(tmp_path):
    root = Path(__file__).parent.parent
    env = {**os.environ, "RECIPE_DB": str(tmp_path / "other.db")}
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from recipe_app.main import DEFAULT_DB_PATH; print(DEFAULT_DB_PATH)",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == str(tmp_path / "other.db")


def test_exclusion_matches_plural_input(recipe_recommender):
    filters = SearchFilters(exclude_ingredients=["peanuts"])
    assert ids(recipe_recommender.search_by_ingredients(["egg"], filters)) == [3]


def test_ingredient_search_other_sort_orders(recipe_recommender):
    by_count = recipe_recommender.search_by_ingredients(
        ["sauce"], sort_by=SortBy.INGREDIENTS
    )
    assert [r["ingredient_count"] for r in by_count] == sorted(
        r["ingredient_count"] for r in by_count
    )
    by_quality = recipe_recommender.search_by_ingredients(
        ["sauce"], sort_by=SortBy.QUALITY
    )
    assert ids(by_quality) == [1, 2, 3]
    by_difficulty = recipe_recommender.search_by_ingredients(
        ["chicken"], sort_by=SortBy.DIFFICULTY
    )
    assert [r["difficulty_level"] for r in by_difficulty] == ["medium", "hard"]


def test_text_search_sort_by_time(recipe_recommender):
    results = recipe_recommender.search_by_text("sauce", sort_by=SortBy.TIME)
    assert [r["total_time"] for r in results] == [20, 30, None]


def test_text_search_empty_query(recipe_recommender):
    assert recipe_recommender.search_by_text("   ") == []


def test_new_meal_types_filter(recipe_recommender):
    dessert = recipe_recommender.browse_recipes(
        SearchFilters(meal_type=MealType.DESSERT)
    )
    assert ids(dessert) == [4]
    assert (
        recipe_recommender.browse_recipes(SearchFilters(meal_type=MealType.DRINK)) == []
    )
    assert {m.value for m in MealType} >= {"side", "drink", "other"}
    assert "main" not in {m.value for m in MealType}


def test_time_filters_exclude_unknown_times(recipe_recommender):
    results = recipe_recommender.browse_recipes(SearchFilters(max_total_time=600))
    assert 3 not in ids(results)  # recipe 3 has no time


def test_query_error_returns_empty_list(recipe_recommender, capsys):
    assert recipe_recommender._query("SELECT * FROM no_such_table", []) == []
    assert "Query error" in capsys.readouterr().out


def test_closed_recommender_is_safe(recipe_recommender):
    recipe_recommender.close()
    recipe_recommender.close()  # closing twice is fine
    assert recipe_recommender.get_database_stats() == {"status": "Not connected"}
    assert recipe_recommender.search_by_ingredients(["pasta"]) == []
    assert recipe_recommender.get_recipe_by_id(1) is None


# ------------------------------------------------------------ partial matches
# Test recipes: 1 pasta/tomato sauce/basil, 2 rice/mixed vegetables/soy sauce,
# 3 chicken breast/rice/egg/soy sauce, 4 peanut butter/confectioner's sugar/egg,
# 5 whole chicken/garlic/lemon.


@pytest.mark.parametrize(
    "n_terms, percent, needed",
    [
        (3, 100, 3),
        (3, 50, 2),  # 1.5 rounds up
        (4, 50, 2),
        (4, 75, 3),
        (10, 70, 7),  # no float rounding surprises
        (1, 10, 1),
        (2, 10, 1),
        (5, 0, 1),  # always at least one
        (5, 150, 5),  # never more than all
    ],
)
def test_min_matches_needed(n_terms, percent, needed):
    assert min_matches_needed(n_terms, percent) == needed


def test_default_still_requires_every_ingredient(recipe_recommender):
    results = recipe_recommender.search_by_ingredients(["rice", "soy", "chicken"])
    assert ids(results) == [3]
    assert results[0]["missing_ingredients"] == []
    assert results[0]["match_percentage"] == 100


def test_partial_match_ranks_full_matches_first(recipe_recommender):
    results = recipe_recommender.search_by_ingredients(
        ["rice", "soy", "chicken"], min_match_percent=50
    )
    assert ids(results) == [3, 2]  # recipe 5 (chicken only, 1 of 3) is below 50%
    assert [round(r["match_percentage"]) for r in results] == [100, 67]
    assert [r["matching_ingredients"] for r in results] == [3, 2]
    assert [r["missing_ingredients"] for r in results] == [[], ["chicken"]]


def test_low_percentage_needs_at_least_one(recipe_recommender):
    results = recipe_recommender.search_by_ingredients(
        ["pasta", "garlic"], min_match_percent=10
    )
    assert sorted(ids(results)) == [1, 5]
    missing = {r["recipe_id"]: r["missing_ingredients"] for r in results}
    assert missing == {1: ["garlic"], 5: ["pasta"]}


def test_partial_match_still_applies_filters_and_exclusions(recipe_recommender):
    terms = ["rice", "soy", "chicken"]
    vegan = recipe_recommender.search_by_ingredients(
        terms, SearchFilters(is_vegan=True), min_match_percent=50
    )
    assert ids(vegan) == [2]
    no_egg = recipe_recommender.search_by_ingredients(
        terms, SearchFilters(exclude_ingredients=["egg"]), min_match_percent=50
    )
    assert ids(no_egg) == [2]


def test_partial_match_with_explicit_sort(recipe_recommender):
    # egg OR rice (1 of 2 is enough): recipes 2, 3, 4, sorted by time, unknown last
    results = recipe_recommender.search_by_ingredients(
        ["egg", "rice"], sort_by=SortBy.TIME, min_match_percent=50
    )
    assert ids(results) == [4, 2, 3]
