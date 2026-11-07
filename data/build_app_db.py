"""
Build a lean, search-optimised database for the Streamlit app.

The full database produced by ``data_processor.py`` (``data/recipes.db``) keeps
a raw copy of the CSV plus columns the app never reads. This script copies only
what the app needs into ``data/recipes_app.db`` and adds an ingredient lookup
index so ingredient searches don't have to scan every recipe's ingredient list.

Tables created:
    recipes             one row per recipe, only the columns the app uses
    ingredient_vocab    one row per distinct ingredient string
    recipe_ingredients  (recipe_id, ingredient_id) pairs

Usage:
    poetry run python -m data.build_app_db
    poetry run python -m data.build_app_db --source data/recipes.db --output data/recipes_app.db
"""

import argparse
import os
import time
from pathlib import Path

import duckdb
from pypika import Query, Table

DATA_DIR = Path(__file__).parent
DEFAULT_SOURCE = DATA_DIR / "recipes.db"
DEFAULT_OUTPUT = DATA_DIR / "recipes_app.db"

# Every column the app reads. Anything else stays in the full database only.
APP_COLUMNS = [
    "recipe_id",
    "title",
    "ingredients_clean",
    "ingredients_original",
    "ingredient_categories",
    "directions",
    "prep_time",
    "cook_time",
    "total_time",
    "servings",
    "difficulty_level",
    "meal_type",
    "ingredient_count",
    "is_vegetarian",
    "is_vegan",
    "is_gluten_free",
    "is_dairy_free",
    "is_nut_free",
    "is_low_carb",
    "is_dessert",
    "is_high_protein",
    "is_low_fat",
    "is_high_fiber",
    "recipe_completeness_score",
    "search_text",
    "ingredient_quantities",
    "link",
    "source",
]


def _sql_str(value: object) -> str:
    """Quote a value as a SQL string literal (ATTACH/SET don't take parameters)."""
    return "'" + str(value).replace("'", "''") + "'"


def build_ingredient_index(con: duckdb.DuckDBPyConnection) -> None:
    """Create ingredient_vocab and recipe_ingredients from the recipes table."""
    con.execute("""
        CREATE OR REPLACE TABLE ingredient_vocab AS
        SELECT row_number() OVER (ORDER BY name)::INTEGER AS ingredient_id, name
        FROM (
            SELECT DISTINCT lower(trim(unnest(ingredients_clean))) AS name
            FROM recipes
        )
        WHERE name IS NOT NULL AND name <> ''
    """)
    # Sorted by ingredient_id so DuckDB's min/max zone maps can skip blocks.
    con.execute("""
        CREATE OR REPLACE TABLE recipe_ingredients AS
        SELECT DISTINCT r.recipe_id, v.ingredient_id
        FROM (
            SELECT recipe_id, lower(trim(unnest(ingredients_clean))) AS name
            FROM recipes
        ) r
        JOIN ingredient_vocab v USING (name)
        ORDER BY v.ingredient_id, r.recipe_id
    """)


def build_app_db(
    source: Path | str = DEFAULT_SOURCE,
    output: Path | str = DEFAULT_OUTPUT,
    memory_limit: str = "2GB",
) -> None:
    """Copy the app's columns from ``source`` into a fresh ``output`` database."""
    source, output = Path(source), Path(output)
    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")

    tmp_output = output.with_suffix(".building.db")
    for stale in (tmp_output, Path(str(tmp_output) + ".wal")):
        if stale.exists():
            stale.unlink()

    # Keep memory low for small machines; DuckDB spills to disk past this.
    con = duckdb.connect(
        str(tmp_output),
        config={
            "memory_limit": memory_limit,
            "preserve_insertion_order": False,
            "temp_directory": str(output.parent / ".duckdb_tmp"),
        },
    )
    try:
        con.execute(f"ATTACH {_sql_str(source)} AS src (READ_ONLY)")

        copy_columns = Query.create_table("recipes").as_select(
            Query.from_(Table("recipes", schema="src")).select(*APP_COLUMNS)
        )
        con.execute(copy_columns.get_sql())
        con.execute("DETACH src")

        build_ingredient_index(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    os.replace(tmp_output, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--memory-limit", default="2GB", help="DuckDB memory cap (default: 2GB)"
    )
    args = parser.parse_args()

    start = time.time()
    print(f"Building {args.output} from {args.source} ...")
    build_app_db(args.source, args.output, args.memory_limit)
    size_gb = Path(args.output).stat().st_size / 1e9
    print(f"Done in {time.time() - start:.0f}s — {size_gb:.2f} GB")


if __name__ == "__main__":
    main()
