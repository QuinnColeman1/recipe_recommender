"""
Process the raw recipe CSV into a cleaned DuckDB database (``recipes`` table).

The cleaning rules live in ``data/cleaning.py``. This module only streams the
CSV in batches, cleans them on several worker processes, writes the results and
removes duplicate recipes. Memory use stays roughly constant regardless of
dataset size.

Usage:
    poetry run python -m data.data_processor                      # full dataset
    poetry run python -m data.data_processor --limit 10000        # quick dev run
    poetry run python -m data.data_processor --db-path data/recipes_v2.db

Then build the app database:
    poetry run python -m data.build_app_db --source <db-path>
"""

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import pyarrow as pa
from pypika import CustomFunction, Query, Table
from pypika import functions as fn

from data.cleaning import process_record

DATA_DIR = Path(__file__).parent
DEFAULT_CSV = DATA_DIR / "full_dataset.csv"
DEFAULT_DB = DATA_DIR / "recipes.db"

_STR_LIST = pa.list_(pa.string())
SCHEMA = pa.schema(
    [
        ("recipe_id", pa.int64()),
        ("title", pa.string()),
        ("link", pa.string()),
        ("source", pa.string()),
        ("directions", pa.string()),
        ("prep_time", pa.int32()),
        ("cook_time", pa.int32()),
        ("total_time", pa.int32()),
        ("servings", pa.int32()),
        ("difficulty_level", pa.string()),
        ("meal_type", pa.string()),
        ("ingredients_clean", _STR_LIST),
        ("ingredients_original", _STR_LIST),
        ("ingredient_quantities", _STR_LIST),
        ("ingredient_categories", _STR_LIST),
        ("ingredient_count", pa.int32()),
        ("is_vegetarian", pa.bool_()),
        ("is_vegan", pa.bool_()),
        ("is_gluten_free", pa.bool_()),
        ("is_dairy_free", pa.bool_()),
        ("is_nut_free", pa.bool_()),
        ("is_low_carb", pa.bool_()),
        ("is_dessert", pa.bool_()),
        ("is_high_protein", pa.bool_()),
        ("is_low_fat", pa.bool_()),
        ("is_high_fiber", pa.bool_()),
        ("has_complete_directions", pa.bool_()),
        ("ingredient_quality_score", pa.float32()),
        ("recipe_completeness_score", pa.float32()),
        ("search_text", pa.string()),
    ]
)

FLAG_COLUMNS = [
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
]


def _sql_str(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _process_chunk(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Worker: clean a list of raw rows (each already carrying ``recipe_id``)."""
    out = []
    for row in rows:
        try:
            record = process_record(row)
        except Exception as e:  # one bad row must not kill the run
            print(f"\nSkipping recipe {row.get('recipe_id')}: {e}")
            continue
        record["recipe_id"] = row["recipe_id"]
        out.append(record)
    return out


def _id_column(columns: List[str]) -> Optional[str]:
    for name in ("column0", "id", "recipe_id", "unnamed_0"):
        if name in columns:
            return name
    return None


def process_csv(
    csv_path: Path,
    db_path: Path,
    limit: Optional[int] = None,
    batch_size: int = 20_000,
    workers: Optional[int] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Clean ``csv_path`` into ``db_path``; returns summary statistics."""
    csv_path, db_path = Path(csv_path), Path(db_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    if db_path.exists() and not overwrite:
        raise FileExistsError(
            f"{db_path} already exists. Pass --overwrite to replace it, "
            "or choose another --db-path."
        )
    workers = workers or min(4, os.cpu_count() or 1)
    # Rows are written to a staging file first and the final, de-duplicated
    # table to a fresh file, because DuckDB files don't shrink after a DROP.
    staging_path = db_path.with_name(db_path.stem + ".staging.db")
    tmp_path = db_path.with_name(db_path.stem + ".building.db")
    for stale in (staging_path, tmp_path):
        for path in (stale, Path(str(stale) + ".wal")):
            if path.exists():
                path.unlink()

    src = duckdb.connect()  # in-memory, only used to stream the CSV
    rel = src.read_csv(
        str(csv_path), header=True, normalize_names=True, sample_size=20000
    )
    if limit:
        rel = rel.limit(int(limit))
    columns = [c.lower() for c in rel.columns]
    missing = {"title", "ingredients", "directions"} - set(columns)
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(sorted(missing))}"
        )
    id_col = _id_column(columns)
    print(f"Columns: {', '.join(columns)} (id column: {id_col or 'row number'})")

    out = duckdb.connect(
        str(staging_path),
        config={
            "memory_limit": "2GB",
            "preserve_insertion_order": False,
            "temp_directory": str(db_path.parent / ".duckdb_tmp"),
        },
    )

    start = time.time()
    processed = 0
    next_id = 0
    created = False
    reader = rel.to_arrow_reader(batch_size)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch in reader:
            rows = batch.to_pylist()
            for row in rows:
                if id_col and row.get(id_col) is not None:
                    row["recipe_id"] = int(row[id_col])
                else:
                    row["recipe_id"] = next_id
                next_id += 1
                # normalize_names renames reserved words, e.g. source -> _source
                if "source" not in row and "_source" in row:
                    row["source"] = row["_source"]
            chunk = max(1, len(rows) // (workers * 4))
            pieces = [rows[i : i + chunk] for i in range(0, len(rows), chunk)]
            cleaned = [rec for part in pool.map(_process_chunk, pieces) for rec in part]

            table = pa.Table.from_pylist(cleaned, schema=SCHEMA)
            out.register("batch_tbl", table)
            if not created:
                out.execute("CREATE TABLE recipes_staging AS SELECT * FROM batch_tbl")
                created = True
            else:
                out.execute("INSERT INTO recipes_staging SELECT * FROM batch_tbl")
            out.unregister("batch_tbl")

            processed += len(rows)
            rate = processed / (time.time() - start)
            print(
                f"\rCleaned {processed:,} recipes ({rate:,.0f}/s)", end="", flush=True
            )
    print()
    src.close()

    if not created:
        out.close()
        staging_path.unlink()
        raise ValueError("No rows were read from the CSV")

    print("Removing duplicates and empty recipes...")
    out.execute(f"ATTACH {_sql_str(tmp_path)} AS final")
    out.execute("""
        CREATE TABLE final.recipes AS
        SELECT * FROM recipes_staging
        WHERE ingredient_count > 0 AND length(directions) > 0 AND length(title) > 0
        QUALIFY row_number() OVER (
            PARTITION BY lower(title), ingredients_clean
            ORDER BY recipe_completeness_score DESC, recipe_id
        ) = 1
    """)
    out.execute("DETACH final")
    out.close()
    staging_path.unlink()

    final = duckdb.connect(str(tmp_path))
    stats = get_statistics(final)
    final.close()
    stats["rows_read"] = processed
    stats["seconds"] = round(time.time() - start)

    os.replace(tmp_path, db_path)
    return stats


median = CustomFunction("median", ["x"])


def get_statistics(con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    recipes = Table("recipes")

    def share(criterion: Any) -> Any:
        return fn.Avg(fn.Cast(criterion, "INT"))

    query = Query.from_(recipes).select(
        fn.Count("*").as_("total_recipes"),
        share(recipes.total_time.notnull()).as_("with_time"),
        share(recipes.servings.notnull()).as_("with_servings"),
        median(recipes.total_time).as_("median_total_time"),
        fn.Avg(recipes.ingredient_count).as_("avg_ingredients"),
        fn.Avg(recipes.recipe_completeness_score).as_("avg_quality"),
        *[share(recipes.field(c)).as_(c) for c in FLAG_COLUMNS],
    )
    row = con.execute(query.get_sql()).fetchone()
    if row is None:  # an aggregate query always returns one row
        raise RuntimeError("Statistics query returned no rows")
    names = [d[0] for d in con.description]
    stats = dict(zip(names, row))
    stats["meal_types"] = dict(
        con.execute(
            "SELECT meal_type, count(*) FROM recipes GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    stats["difficulty"] = dict(
        con.execute(
            "SELECT difficulty_level, count(*) FROM recipes GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    return stats


def print_statistics(stats: Dict[str, Any]) -> None:
    total = stats["total_recipes"]
    print(
        f"\nRead {stats['rows_read']:,} rows -> kept {total:,} recipes "
        f"({stats['rows_read'] - total:,} duplicates/empty removed) in {stats['seconds']}s"
    )
    print(
        f"With a cooking time: {stats['with_time']:.1%} "
        f"(median {stats['median_total_time']} min) | with servings: {stats['with_servings']:.1%}"
    )
    print(
        f"Avg ingredients: {stats['avg_ingredients']:.1f} | avg quality: {stats['avg_quality']:.2f}"
    )
    print("Labels: " + ", ".join(f"{c[3:]} {stats[c]:.0%}" for c in FLAG_COLUMNS))
    print(
        "Meal types: "
        + ", ".join(f"{k} {v / total:.0%}" for k, v in stats["meal_types"].items())
    )
    print(
        "Difficulty: "
        + ", ".join(f"{k} {v / total:.0%}" for k, v in stats["difficulty"].items())
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean the recipe CSV into a DuckDB database."
    )
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV))
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process the first N rows"
    )
    parser.add_argument("--batch-size", type=int, default=20_000)
    parser.add_argument(
        "--workers", type=int, default=None, help="Worker processes (default: up to 4)"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace --db-path if it exists"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    print(f"Cleaning {args.csv_path} -> {args.db_path}")
    stats = process_csv(
        Path(args.csv_path),
        Path(args.db_path),
        limit=args.limit,
        batch_size=args.batch_size,
        workers=args.workers,
        overwrite=args.overwrite,
    )
    print_statistics(stats)
    print(f"\nNext: poetry run python -m data.build_app_db --source {args.db_path}")


if __name__ == "__main__":
    main()
