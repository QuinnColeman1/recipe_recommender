"""Recipe Recommender package."""

# Import key components to make them available at the package level
from .main import (
    EnhancedRecipeRecommender,
    SearchFilters,
    MealType,
    SortBy,
    DifficultyLevel
)

# Don't import from streamlit_app here to avoid circular imports
# Import the functions directly in the test files instead

__all__ = [
    'EnhancedRecipeRecommender',
    'SearchFilters',
    'MealType',
    'SortBy',
    'DifficultyLevel'
]