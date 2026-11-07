"""
Recipe search over the DuckDB app database built by ``data/build_app_db.py``.
"""

import os
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import duckdb
from pypika import (
    AliasedQuery,
    Case,
    Criterion,
    CustomFunction,
    Field,
    Order,
    Parameter,
    Query,
    Table,
)
from pypika import functions as fn
from pypika.queries import QueryBuilder
from pypika.terms import Term

# Override with the RECIPE_DB environment variable, e.g. to try a rebuilt database.
DEFAULT_DB_PATH = Path(
    os.environ.get("RECIPE_DB")
    or Path(__file__).parent.parent / "data" / "recipes_app.db"
)
REQUIRED_TABLES = {"recipes", "ingredient_vocab", "recipe_ingredients"}


class MealType(Enum):
    ANY = "any"
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    DESSERT = "dessert"
    SNACK = "snack"
    SIDE = "side"
    DRINK = "drink"
    OTHER = "other"


class DifficultyLevel(Enum):
    ANY = "any"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SortBy(Enum):
    RELEVANCE = "relevance"
    TIME = "time"
    QUALITY = "quality"
    INGREDIENTS = "ingredients"
    DIFFICULTY = "difficulty"


@dataclass
class SearchFilters:
    """Filters shared by every search mode."""

    # Dietary restrictions
    is_vegetarian: Optional[bool] = None
    is_vegan: Optional[bool] = None
    is_gluten_free: Optional[bool] = None
    is_dairy_free: Optional[bool] = None
    is_nut_free: Optional[bool] = None
    is_low_carb: Optional[bool] = None

    # Nutritional preferences
    is_high_protein: Optional[bool] = None
    is_low_fat: Optional[bool] = None
    is_high_fiber: Optional[bool] = None

    # Time constraints (in minutes)
    max_total_time: Optional[int] = None
    max_prep_time: Optional[int] = None
    max_cook_time: Optional[int] = None

    # Other filters
    meal_type: MealType = MealType.ANY
    difficulty_level: DifficultyLevel = DifficultyLevel.ANY
    min_quality_score: float = 0.0
    exclude_ingredients: List[str] = field(default_factory=list)


_BOOLEAN_FILTERS = [
    "is_vegetarian",
    "is_vegan",
    "is_gluten_free",
    "is_dairy_free",
    "is_nut_free",
    "is_low_carb",
    "is_high_protein",
    "is_low_fat",
    "is_high_fiber",
]

_TIME_FILTERS = {
    "max_total_time": "total_time",
    "max_prep_time": "prep_time",
    "max_cook_time": "cook_time",
}

# ------------------------------------------------------------- query building
# Queries are built with PyPika; every value comes in as a named parameter.

RECIPES = Table("recipes", alias="r")
VOCAB = Table("ingredient_vocab", alias="v")
RECIPE_INGREDIENTS = Table("recipe_ingredients", alias="ri")

contains = CustomFunction("contains", ["string", "search"])
greatest = CustomFunction("greatest", ["a", "b"])
unnest = CustomFunction("unnest", ["list"])
generate_subscripts = CustomFunction("generate_subscripts", ["list", "dim"])
list_agg = CustomFunction("list", ["value"])  # DuckDB aggregate: values -> list

# Columns returned for every result (the score is renamed for the UI).
_RESULT_COLUMNS = [
    "recipe_id",
    "title",
    "ingredients_clean",
    "ingredients_original",
    "ingredient_categories",
    "ingredient_quantities",
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
    "link",
    "source",
]
_LIST_COLUMNS = (
    "ingredients_clean",
    "ingredients_original",
    "ingredient_categories",
    "ingredient_quantities",
)


def _result_columns() -> List[Term]:
    return [RECIPES.field(c) for c in _RESULT_COLUMNS] + [
        RECIPES.recipe_completeness_score.as_("quality_score")
    ]


_DIFFICULTY_RANK = (
    Case()
    .when(RECIPES.difficulty_level == "easy", 1)
    .when(RECIPES.difficulty_level == "medium", 2)
    .when(RECIPES.difficulty_level == "hard", 3)
    .else_(4)
)
_ORDER_BY: Dict[SortBy, List[Tuple[Term, Order]]] = {
    SortBy.TIME: [(RECIPES.total_time, Order.asc)],  # DuckDB puts NULLs last
    SortBy.QUALITY: [(RECIPES.recipe_completeness_score, Order.desc)],
    SortBy.INGREDIENTS: [(RECIPES.ingredient_count, Order.asc)],
    SortBy.DIFFICULTY: [(_DIFFICULTY_RANK, Order.asc)],
}


def _ordered(query: QueryBuilder, order: List[Tuple[Term, Order]]) -> QueryBuilder:
    """Apply ORDER BY terms plus recipe_id as a stable tiebreaker."""
    for term, direction in order + [(RECIPES.recipe_id, Order.asc)]:
        query = query.orderby(term, order=direction)
    return query


class _Params:
    """Collects values and hands out named placeholders ($p0, $p1, ...)."""

    def __init__(self) -> None:
        self.values: Dict[str, Any] = {}

    def add(self, value: Any) -> Parameter:
        name = "p" + str(len(self.values))
        self.values[name] = value
        return Parameter("$" + name)


_PLURAL_ENDINGS = [
    ("ies", "y"),
    ("oes", "o"),
    ("ches", "ch"),
    ("shes", "sh"),
    ("sses", "ss"),
    ("xes", "x"),
]


def _singular(term: str) -> str:
    """Rough singular form so 'tomatoes' also matches 'tomato paste'."""
    for plural, single in _PLURAL_ENDINGS:
        if term.endswith(plural) and len(term) > len(plural) + 2:
            return term[: -len(plural)] + single
    if term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        return term[:-1]
    return term


def _clean_terms(terms: Optional[List[str]]) -> List[str]:
    """Lowercase, trim and de-duplicate search terms, keeping order."""
    seen: Dict[str, None] = {}
    for term in terms or []:
        term = term.strip().lower()
        if term:
            seen[term] = None
    return list(seen)


def min_matches_needed(n_terms: int, min_match_percent: int) -> int:
    """How many of ``n_terms`` a recipe must contain: the percentage rounded up, 1..n."""
    needed = -(-n_terms * int(min_match_percent) // 100)  # ceiling, integer maths
    return max(1, min(n_terms, needed))


def _matches(column: Term, term: str, params: _Params) -> Criterion:
    """column contains the term or its singular form."""
    return contains(column, params.add(term)) | contains(
        column, params.add(_singular(term))
    )


class EnhancedRecipeRecommender:
    """Recipe recommender backed by a read-only DuckDB database."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = str(db_path if db_path is not None else DEFAULT_DB_PATH)
        self.con: Optional[duckdb.DuckDBPyConnection] = None
        self.is_connected = False
        self.connection_error: Optional[str] = None
        self.connect_to_database()

    def connect_to_database(self) -> None:
        """Open the database read-only and check it has the app's tables."""
        if not Path(self.db_path).exists():
            self.connection_error = f"Database not found: {self.db_path}"
            return
        try:
            self.con = duckdb.connect(self.db_path, read_only=True)
            tables = {row[0] for row in self.con.execute("SHOW TABLES").fetchall()}
            missing = REQUIRED_TABLES - tables
            if missing:
                self.connection_error = (
                    f"Database is missing tables {sorted(missing)}. "
                    "Build it with: poetry run python -m data.build_app_db"
                )
                self.close()
                return
            self.is_connected = True
        except Exception as e:  # pragma: no cover - depends on the file on disk
            self.connection_error = f"Could not connect to database: {e}"
            self.close()

    def close(self) -> None:
        if self.con is not None:
            self.con.close()
        self.con = None
        self.is_connected = False

    # ------------------------------------------------------------------ helpers

    def _query(self, query: QueryBuilder, params: _Params) -> List[Dict[str, Any]]:
        """Run a query on its own cursor (safe across Streamlit threads)."""
        if not self.is_connected or self.con is None:
            return []
        cur = self.con.cursor()
        try:
            cur.execute(query.get_sql(), params.values)
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        except Exception as e:
            print(f"Query error: {e}")
            return []
        finally:
            cur.close()
        for row in rows:
            for key in _LIST_COLUMNS:
                if key in row and row[key] is None:
                    row[key] = []
        return rows

    @staticmethod
    def _filter_criterion(filters: SearchFilters, params: _Params) -> Criterion:
        """WHERE condition (on alias ``r``) for every filter that is set."""
        conditions: List[Criterion] = [
            RECIPES.recipe_completeness_score >= params.add(filters.min_quality_score)
        ]

        for name in _BOOLEAN_FILTERS:
            value = getattr(filters, name)
            if value is not None:
                conditions.append(RECIPES.field(name) == params.add(value))

        for name, column in _TIME_FILTERS.items():
            value = getattr(filters, name)
            if value is not None:  # NULL times never match
                conditions.append(RECIPES.field(column) <= params.add(value))

        if filters.meal_type != MealType.ANY:
            conditions.append(RECIPES.meal_type == params.add(filters.meal_type.value))

        if filters.difficulty_level != DifficultyLevel.ANY:
            conditions.append(
                RECIPES.difficulty_level == params.add(filters.difficulty_level.value)
            )

        excluded = _clean_terms(filters.exclude_ingredients)
        if excluded:
            has_excluded = (
                Query.from_(RECIPE_INGREDIENTS)
                .join(VOCAB)
                .on(RECIPE_INGREDIENTS.ingredient_id == VOCAB.ingredient_id)
                .select(RECIPE_INGREDIENTS.recipe_id)
                .where(
                    Criterion.any([_matches(VOCAB.name, t, params) for t in excluded])
                )
            )
            conditions.append(RECIPES.recipe_id.notin(has_excluded))

        return Criterion.all(conditions)

    # ----------------------------------------------------------------- queries

    def get_database_stats(self) -> Dict[str, Any]:
        """Summary statistics for the whole database."""
        if not self.is_connected:
            return {"status": "Not connected"}

        def count_true(column: str) -> Term:
            return fn.Sum(Case().when(RECIPES.field(column) == True, 1).else_(0))  # noqa: E712

        query = Query.from_(RECIPES).select(
            fn.Count("*").as_("total_recipes"),
            fn.Count(RECIPES.meal_type).distinct().as_("meal_types"),
            fn.Avg(RECIPES.ingredient_count).as_("avg_ingredients"),
            fn.Avg(RECIPES.total_time).as_("avg_time"),
            fn.Avg(RECIPES.recipe_completeness_score).as_("avg_quality"),
            count_true("is_vegetarian").as_("vegetarian_count"),
            count_true("is_vegan").as_("vegan_count"),
            count_true("is_gluten_free").as_("gluten_free_count"),
        )
        rows = self._query(query, _Params())
        if not rows:
            return {"status": "Error"}
        stats = rows[0]
        for key in ("vegetarian_count", "vegan_count", "gluten_free_count"):
            stats[key] = int(stats[key] or 0)
        stats["avg_ingredients"] = round(stats["avg_ingredients"] or 0, 1)
        stats["avg_time"] = round(stats["avg_time"] or 0)
        stats["avg_quality"] = round(stats["avg_quality"] or 0, 2)
        return stats

    def search_by_ingredients(
        self,
        ingredients: List[str],
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        limit: int = 10,
        min_match_percent: int = 100,
    ) -> List[Dict]:
        """
        Recipes containing at least ``min_match_percent`` of the ingredients
        given (rounded up; 100 = every ingredient). Matching is by substring,
        so "chicken" also matches "chicken breasts".
        """
        filters = filters or SearchFilters()
        terms = _clean_terms(ingredients)
        if not terms:
            return []
        needed = min_matches_needed(len(terms), min_match_percent)
        params = _Params()

        # terms(term_idx, term, singular) from two list parameters
        term_list = params.add(terms)
        singular_list = params.add([_singular(t) for t in terms])
        terms_cte = Query.select(
            generate_subscripts(term_list, 1).as_("term_idx"),
            unnest(term_list).as_("term"),
            unnest(singular_list).as_("singular"),
        )
        t = AliasedQuery("terms")

        # ingredient ids matching each term
        matched_cte = (
            Query.from_(VOCAB)
            .join(t)
            .on(contains(VOCAB.name, t.term) | contains(VOCAB.name, t.singular))
            .select(VOCAB.ingredient_id, t.term_idx)
            .distinct()
        )
        m = AliasedQuery("matched_ids")

        # recipes containing enough of the terms
        match_count = fn.Count(m.term_idx).distinct()
        hits_cte = (
            Query.from_(RECIPE_INGREDIENTS)
            .join(m)
            .on(RECIPE_INGREDIENTS.ingredient_id == m.ingredient_id)
            .groupby(RECIPE_INGREDIENTS.recipe_id)
            .select(
                RECIPE_INGREDIENTS.recipe_id,
                match_count.as_("match_score"),
                list_agg(m.term_idx).as_("matched_terms"),
            )
            .having(match_count >= params.add(needed))
        )
        h = AliasedQuery("hits")

        # Relevance: recipes using more of your ingredients first, then those
        # named after them, then those needing fewest extra ingredients, then
        # quality.
        title_hits: Term = fn.Cast(
            _matches(fn.Lower(RECIPES.title), terms[0], params), "INT"
        )
        for term in terms[1:]:
            title_hits = title_hits + fn.Cast(
                _matches(fn.Lower(RECIPES.title), term, params), "INT"
            )
        relevance: List[Tuple[Term, Order]] = [
            (h.match_score, Order.desc),
            (Field("title_hits"), Order.desc),
            (h.match_score * 1.0 / greatest(RECIPES.ingredient_count, 1), Order.desc),
            (RECIPES.recipe_completeness_score, Order.desc),
        ]

        query = (
            Query.with_(terms_cte, "terms")
            .with_(matched_cte, "matched_ids")
            .with_(hits_cte, "hits")
            .from_(RECIPES)
            .join(h)
            .on(RECIPES.recipe_id == h.recipe_id)
            .select(
                *_result_columns(),
                h.match_score,
                h.matched_terms,
                title_hits.as_("title_hits"),
            )
            .where(self._filter_criterion(filters, params))
            .limit(int(limit))
        )
        results = self._query(
            _ordered(query, _ORDER_BY.get(sort_by, relevance)), params
        )
        for row in results:
            matched = set(row.pop("matched_terms") or [])  # 1-based term positions
            row["matching_ingredients"] = row["match_score"]
            row["match_percentage"] = row["match_score"] / len(terms) * 100
            row["missing_ingredients"] = [
                term for i, term in enumerate(terms, 1) if i not in matched
            ]
        return results

    def search_by_text(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        limit: int = 10,
    ) -> List[Dict]:
        """Recipes whose title or ingredients contain the query text."""
        filters = filters or SearchFilters()
        text = query.strip().lower()
        if not text:
            return []
        params = _Params()
        q = params.add(text)
        relevance: List[Tuple[Term, Order]] = [
            (contains(fn.Lower(RECIPES.title), q), Order.desc),  # title matches first
            (RECIPES.recipe_completeness_score, Order.desc),
        ]
        sql = (
            Query.from_(RECIPES)
            .select(*_result_columns())
            .where(
                contains(RECIPES.search_text, q)
                & self._filter_criterion(filters, params)
            )
            .limit(int(limit))
        )
        return self._query(_ordered(sql, _ORDER_BY.get(sort_by, relevance)), params)

    def browse_recipes(
        self,
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.QUALITY,
        limit: int = 20,
    ) -> List[Dict]:
        """All recipes matching the filters, without an ingredient requirement."""
        filters = filters or SearchFilters()
        params = _Params()
        query = (
            Query.from_(RECIPES)
            .select(*_result_columns())
            .where(self._filter_criterion(filters, params))
            .limit(int(limit))
        )
        order = _ORDER_BY.get(sort_by, _ORDER_BY[SortBy.QUALITY])
        return self._query(_ordered(query, order), params)

    def get_quick_recipes(
        self,
        max_time: int = 30,
        limit: int = 10,
        filters: Optional[SearchFilters] = None,
    ) -> List[Dict]:
        """Recipes with a known total time of at most ``max_time`` minutes."""
        filters = replace(
            filters or SearchFilters(min_quality_score=0.7), max_total_time=max_time
        )
        return self.browse_recipes(filters=filters, sort_by=SortBy.TIME, limit=limit)

    def get_recipe_by_id(self, recipe_id: int) -> Optional[Dict[str, Any]]:
        """A single recipe with all stored columns."""
        params = _Params()
        query = (
            Query.from_(RECIPES)
            .select("*")
            .where(RECIPES.recipe_id == params.add(recipe_id))
        )
        rows = self._query(query, params)
        return rows[0] if rows else None
