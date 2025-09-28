"""Tests for main.py functionality."""
import sys
import os
import pytest

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the module under test
from streamlit.main import (
    EnhancedRecipeRecommender,
    SearchFilters,
    MealType,
    SortBy,
    DifficultyLevel
)

def test_initialization(recipe_recommender):
    """Test that the recommender initializes correctly."""
    assert recipe_recommender is not None
    assert recipe_recommender.is_connected is True

def test_get_database_stats(recipe_recommender):
    """Test getting database statistics."""
    stats = recipe_recommender.get_database_stats()
    assert 'total_recipes' in stats
    assert stats['total_recipes'] > 0

def test_search_by_ingredients(recipe_recommender, search_filters):
    """Test searching recipes by ingredients."""
    # Test basic search
    results = recipe_recommender.search_by_ingredients(
        ingredients=["pasta", "tomato"],
        filters=search_filters,
        sort_by=SortBy.RELEVANCE,
        limit=5
    )
    assert len(results) > 0
    assert 'Pasta' in results[0]['title']

def test_search_by_text(recipe_recommender, search_filters):
    """Test text-based recipe search."""
    results = recipe_recommender.search_by_text(
        query="pasta",
        filters=search_filters,
        sort_by=SortBy.RELEVANCE,
        limit=5
    )
    assert len(results) > 0
    assert 'Pasta' in results[0]['title']

def test_get_recipe_by_id(recipe_recommender):
    """Test getting a recipe by ID."""
    recipe = recipe_recommender.get_recipe_by_id(1)
    assert recipe is not None
    assert recipe['recipe_id'] == 1
    assert 'Pasta' in recipe['title']

def test_browse_recipes(recipe_recommender, search_filters):
    """Test browsing recipes with filters."""
    # Test with no filters
    results = recipe_recommender.browse_recipes(
        filters=search_filters,
        sort_by=SortBy.QUALITY,
        limit=5
    )
    assert len(results) > 0
    
    # Test with filters
    search_filters.meal_type = MealType.DINNER
    search_filters.difficulty = DifficultyLevel.EASY
    
    results = recipe_recommender.browse_recipes(
        filters=search_filters,
        sort_by=SortBy.QUALITY,
        limit=5
    )
    assert len(results) > 0

def test_get_quick_recipes(recipe_recommender):
    """Test getting quick recipes."""
    results = recipe_recommender.get_quick_recipes(max_time=30, limit=5)
    assert len(results) > 0
    assert results[0]['total_time'] <= 30
