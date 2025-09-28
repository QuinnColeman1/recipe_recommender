"""
Enhanced Main module for handling recipe search with DuckDB integration
"""

import sys
import duckdb
from pathlib import Path
from typing import List, Dict, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum

# Add the parent directory to the path
sys.path.append(str(Path(__file__).parent.parent))


class MealType(Enum):
    ANY = "any"
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    DESSERT = "dessert"
    SNACK = "snack"
    MAIN = "main"


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
    """Dataclass for search filters"""

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
    exclude_ingredients: Optional[List[str]] = None

    def __post_init__(self):
        if self.exclude_ingredients is None:
            self.exclude_ingredients = []


class EnhancedRecipeRecommender:
    """Enhanced recipe recommender using DuckDB"""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """Initialize with database connection"""
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "recipes.db"
        elif not isinstance(db_path, Path):
            db_path = Path(db_path)

        self.db_path = str(db_path)  # Store as string for compatibility
        self.con: Optional[duckdb.DuckDBPyConnection] = None
        self.is_connected = False

        # Try to connect to database
        self.connect_to_database()

    def connect_to_database(self) -> None:
        """Connect to the DuckDB database"""
        try:
            self.con = duckdb.connect(str(self.db_path), read_only=True)
            # Check if recipes table exists
            if self.con is not None:  # Ensure connection was successful
                tables = self.con.execute("SHOW TABLES").fetchall()
                if ("recipes",) in tables:
                    self.is_connected = True
                    print(f"Connected to database: {self.db_path}")
                    return

            print(f"Database found but no recipes table: {self.db_path}")
            self.is_connected = False
            if self.con:
                self.con.close()
                self.con = None
        except Exception as e:
            print(f"Could not connect to database: {e}")
            self.is_connected = False
            if self.con:
                self.con.close()
                self.con = None

    def get_database_stats(self) -> Dict[str, Any]:
        """Get statistics about the database"""
        if not self.is_connected or self.con is None:
            return {"status": "Not connected"}

        try:
            stats = self.con.execute("""
                SELECT 
                    COUNT(*) as total_recipes,
                    COUNT(DISTINCT meal_type) as meal_types,
                    AVG(ingredient_count) as avg_ingredients,
                    AVG(total_time) as avg_time,
                    AVG(recipe_completeness_score) as avg_quality,
                    SUM(CASE WHEN is_vegetarian THEN 1 ELSE 0 END) as vegetarian_count,
                    SUM(CASE WHEN is_vegan THEN 1 ELSE 0 END) as vegan_count,
                    SUM(CASE WHEN is_gluten_free THEN 1 ELSE 0 END) as gluten_free_count
                FROM recipes
            """).fetchone()

            return {
                "total_recipes": stats[0],
                "meal_types": stats[1],
                "avg_ingredients": round(stats[2], 1) if stats[2] else 0,
                "avg_time": round(stats[4], 0) if stats[4] else 0,
                "avg_quality": round(stats[4], 2) if stats[4] else 0,
                "vegetarian_count": stats[5],
                "vegan_count": stats[6],
                "gluten_free_count": stats[7],
            }
        except Exception as e:
            return {"status": "Error", "error": str(e)}

    def search_by_ingredients(
        self,
        ingredients: List[str],
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        limit: int = 10,
    ) -> List[Dict]:
        """Search recipes by ingredients with advanced filtering"""
        if not self.is_connected or self.con is None:
            return []

        if filters is None:
            filters = SearchFilters()

        # Clean and prepare ingredients
        ingredients = [ing.strip().lower() for ing in ingredients if ing.strip()]
        if not ingredients:
            return []

        # Build WHERE clause for filters
        where_clauses = ["recipe_completeness_score >= ?"]
        params = [filters.min_quality_score]

        # Add dietary filters
        if filters.is_vegetarian is not None:
            where_clauses.append("is_vegetarian = ?")
            params.append(filters.is_vegetarian)
        if filters.is_vegan is not None:
            where_clauses.append("is_vegan = ?")
            params.append(filters.is_vegan)
        if filters.is_gluten_free is not None:
            where_clauses.append("is_gluten_free = ?")
            params.append(filters.is_gluten_free)
        if filters.is_dairy_free is not None:
            where_clauses.append("is_dairy_free = ?")
            params.append(filters.is_dairy_free)
        if filters.is_nut_free is not None:
            where_clauses.append("is_nut_free = ?")
            params.append(filters.is_nut_free)
        if filters.is_low_carb is not None:
            where_clauses.append("is_low_carb = ?")
            params.append(filters.is_low_carb)

        # Add nutritional filters
        if filters.is_high_protein is not None:
            where_clauses.append("is_high_protein = ?")
            params.append(filters.is_high_protein)
        if filters.is_low_fat is not None:
            where_clauses.append("is_low_fat = ?")
            params.append(filters.is_low_fat)
        if filters.is_high_fiber is not None:
            where_clauses.append("is_high_fiber = ?")
            params.append(filters.is_high_fiber)

        # Add time filters
        if filters.max_total_time is not None:
            where_clauses.append("total_time <= ? AND total_time IS NOT NULL")
            params.append(filters.max_total_time)
        if filters.max_prep_time is not None:
            where_clauses.append("prep_time <= ? AND prep_time IS NOT NULL")
            params.append(filters.max_prep_time)
        if filters.max_cook_time is not None:
            where_clauses.append("cook_time <= ? AND cook_time IS NOT NULL")
            params.append(filters.max_cook_time)

        # Add meal type filter
        if filters.meal_type != MealType.ANY:
            where_clauses.append("meal_type = ?")
            params.append(filters.meal_type.value)

        # Add difficulty filter
        if filters.difficulty_level != DifficultyLevel.ANY:
            where_clauses.append("difficulty_level = ?")
            params.append(filters.difficulty_level.value)

        # Build the ingredient matching conditions
        ingredient_conditions = []
        for ing in ingredients:
            ingredient_conditions.append(f"""
                EXISTS (
                    SELECT 1 FROM (
                        SELECT unnest(ingredients_clean) as ingredient
                    ) AS ing_list
                    WHERE ing_list.ingredient LIKE '%{ing}%'
                )
            """)

        # Exclude ingredients
        if filters.exclude_ingredients:
            for exc_ing in filters.exclude_ingredients:
                if exc_ing.strip():  # Skip empty strings
                    ingredient_conditions.append(f"""
                        NOT EXISTS (
                            SELECT 1 FROM (
                                SELECT unnest(ingredients_clean) as ingredient
                            ) AS ing_list
                            WHERE ing_list.ingredient LIKE '%{exc_ing.lower().strip()}%'
                        )
                    """)

        # Combine all conditions
        where_clause = " AND ".join(where_clauses)
        if ingredient_conditions:
            where_clause += " AND " + " AND ".join(ingredient_conditions)

        # Calculate match score
        match_score_calc = " + ".join(
            [
                f"""
            CASE WHEN EXISTS (
                SELECT 1 FROM (SELECT unnest(ingredients_clean) as ingredient) AS ing_list
                WHERE ing_list.ingredient LIKE '%{ing}%'
            ) THEN 1 ELSE 0 END
            """
                for ing in ingredients
            ]
        )

        # Determine ORDER BY clause
        if sort_by == SortBy.RELEVANCE:
            order_by = f"({match_score_calc}) DESC, recipe_completeness_score DESC"
        elif sort_by == SortBy.TIME:
            order_by = "COALESCE(total_time, 999999) ASC"
        elif sort_by == SortBy.QUALITY:
            order_by = "recipe_completeness_score DESC"
        elif sort_by == SortBy.INGREDIENTS:
            order_by = "ingredient_count ASC"
        elif sort_by == SortBy.DIFFICULTY:
            order_by = "CASE difficulty_level WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 WHEN 'hard' THEN 3 END ASC"
        else:  # This should never be reached as all SortBy values are handled
            raise ValueError(f"Unexpected sort_by value: {sort_by}")

        # Build and execute query
        query = f"""
            SELECT 
                recipe_id,
                title,
                ingredients_clean,
                ingredients_original,
                ingredient_categories,
                directions,
                prep_time,
                cook_time,
                total_time,
                servings,
                difficulty_level,
                meal_type,
                ingredient_count,
                is_vegetarian,
                is_vegan,
                is_gluten_free,
                is_dairy_free,
                is_nut_free,
                is_low_carb,
                is_dessert,
                is_high_protein,
                is_low_fat,
                is_high_fiber,
                recipe_completeness_score,
                ({match_score_calc}) as match_score
            FROM recipes
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(limit)

        try:
            results = self.con.execute(query, params).fetchall()

            # Format results
            formatted_results = []
            for row in results:
                formatted_results.append(
                    {
                        "recipe_id": row[0],
                        "title": row[1],
                        "ingredients_clean": row[2] if row[2] else [],
                        "ingredients_original": row[3] if row[3] else [],
                        "ingredient_categories": row[4] if row[4] else [],
                        "directions": row[5],
                        "prep_time": row[6],
                        "cook_time": row[7],
                        "total_time": row[8],
                        "servings": row[9],
                        "difficulty_level": row[10],
                        "meal_type": row[11],
                        "ingredient_count": row[12],
                        "is_vegetarian": row[13],
                        "is_vegan": row[14],
                        "is_gluten_free": row[15],
                        "is_dairy_free": row[16],
                        "is_nut_free": row[17],
                        "is_low_carb": row[18],
                        "is_dessert": row[19],
                        "is_high_protein": row[20],
                        "is_low_fat": row[21],
                        "is_high_fiber": row[22],
                        "quality_score": row[23],
                        "match_score": row[24],
                        "matching_ingredients": row[
                            24
                        ],  # Count of matching ingredients
                        "match_percentage": (row[24] / len(ingredients) * 100)
                        if len(ingredients) > 0
                        else 0,
                    }
                )

            return formatted_results

        except Exception as e:
            print(f"Query error: {e}")
            return []

    def search_by_text(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.RELEVANCE,
        limit: int = 10,
    ) -> List[Dict]:
        """Search recipes using text search on title and ingredients"""
        if not self.is_connected or self.con is None:
            return []

        if filters is None:
            filters = SearchFilters()

        query = query.strip().lower()
        if not query:
            return []

        # Using query parameters directly in the SQL query for safety

        # Build and execute simpler text search query
        query_sql = """
            SELECT 
                recipe_id, title, ingredients_clean, ingredients_original,
                directions, total_time, difficulty_level, meal_type,
                ingredient_count, is_vegetarian, is_vegan, is_gluten_free,
                is_dairy_free, is_nut_free, is_low_carb, is_high_protein,
                is_low_fat, is_high_fiber, recipe_completeness_score
            FROM recipes
            WHERE search_text LIKE ?
            AND recipe_completeness_score >= ?
            ORDER BY recipe_completeness_score DESC
            LIMIT ?
        """

        try:
            results = self.con.execute(
                query_sql, [f"%{query}%", filters.min_quality_score, limit]
            ).fetchall()

            formatted_results = []
            for row in results:
                formatted_results.append(
                    {
                        "recipe_id": row[0],
                        "title": row[1],
                        "ingredients_clean": row[2] if row[2] else [],
                        "ingredients_original": row[3] if row[3] else [],
                        "directions": row[4],
                        "total_time": row[5],
                        "difficulty_level": row[6],
                        "meal_type": row[7],
                        "ingredient_count": row[8],
                        "is_vegetarian": row[9],
                        "is_vegan": row[10],
                        "is_gluten_free": row[11],
                        "is_dairy_free": row[12],
                        "is_nut_free": row[13],
                        "is_low_carb": row[14],
                        "is_high_protein": row[15],
                        "is_low_fat": row[16],
                        "is_high_fiber": row[17],
                        "quality_score": row[18],
                    }
                )

            return formatted_results

        except Exception as e:
            print(f"Text search error: {e}")
            return []

    def get_quick_recipes(self, max_time: int = 30, limit: int = 10) -> List[Dict]:
        """Get quick recipes under specified time"""
        filters = SearchFilters(max_total_time=max_time, min_quality_score=0.7)
        # Use empty ingredient list to get all recipes matching filters
        return self.browse_recipes(filters=filters, sort_by=SortBy.TIME, limit=limit)

    def browse_recipes(
        self,
        filters: Optional[SearchFilters] = None,
        sort_by: SortBy = SortBy.QUALITY,
        limit: int = 20,
    ) -> List[Dict]:
        """Browse all recipes with filters but no specific ingredient requirements"""
        if not self.is_connected or self.con is None:
            return []

        if filters is None:
            filters = SearchFilters()

        # Simple browse query with quality filter
        query = """
            SELECT 
                recipe_id, title, ingredients_clean, total_time,
                difficulty_level, meal_type, ingredient_count,
                is_vegetarian, is_vegan, recipe_completeness_score
            FROM recipes
            WHERE recipe_completeness_score >= ?
            ORDER BY recipe_completeness_score DESC
            LIMIT ?
        """

        try:
            results = self.con.execute(
                query, [filters.min_quality_score, limit]
            ).fetchall()

            formatted_results = []
            for row in results:
                formatted_results.append(
                    {
                        "recipe_id": row[0],
                        "title": row[1],
                        "ingredients_clean": row[2] if row[2] else [],
                        "total_time": row[3],
                        "difficulty_level": row[4],
                        "meal_type": row[5],
                        "ingredient_count": row[6],
                        "is_vegetarian": row[7],
                        "is_vegan": row[8],
                        "quality_score": row[9],
                    }
                )

            return formatted_results

        except Exception as e:
            print(f"Browse error: {e}")
            return []

    def get_recipe_by_id(self, recipe_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific recipe by ID"""
        if not self.is_connected or self.con is None:
            return None

        try:
            result = self.con.execute(
                """
                SELECT * FROM recipes 
                WHERE recipe_id = ?
                """,
                [recipe_id],
            ).fetchone()

            if result and self.con.description:
                # Convert to dict with column names
                columns = [d[0] for d in self.con.description]
                return dict(zip(columns, result))
            return None
        except Exception as e:
            print(f"Error getting recipe {recipe_id}: {e}")
            return None
