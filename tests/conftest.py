"""Test configuration and fixtures for recipe recommender tests."""
import os
import sys
import pytest
import duckdb
import tempfile
import shutil
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the modules under test
from streamlit.main import (
    EnhancedRecipeRecommender,
    SearchFilters,
    MealType,
    SortBy,
    DifficultyLevel
)

@pytest.fixture(scope="module")
def test_db_path():
    """Create a temporary database for testing."""
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_recipes.db"
    
    # Create a test database with a simple schema
    conn = duckdb.connect(str(db_path))
    
    # Create tables (simplified version of your actual schema)
    conn.execute("""
    CREATE TABLE recipes (
        recipe_id INTEGER PRIMARY KEY,
        title VARCHAR,
        ingredients_original TEXT,
        ingredients_clean TEXT,
        directions TEXT,
        link VARCHAR,
        source VARCHAR,
        NER TEXT,
        total_time INTEGER,
        servings INTEGER,
        cuisine_path VARCHAR,
        nutrition TEXT,
        ingredient_categories TEXT,
        difficulty_level VARCHAR,
        meal_type VARCHAR,
        recipe_completeness_score FLOAT,
        ingredient_count INTEGER
    )
    """)
    
    # Insert some test data
    test_recipes = [
        (1, 'Pasta with Tomato Sauce', 'pasta, tomato sauce', 'pasta, tomato sauce', 
         'Cook pasta. Add sauce.', 'http://example.com', 'test', '["pasta", "tomato sauce"]', 
         20, 2, 'Italian', '{}', '{"pasta": "pasta", "tomato sauce": "sauces"}', 
         'easy', 'dinner', 0.95, 2),
        (2, 'Vegetable Stir Fry', 'rice, mixed vegetables, soy sauce', 
         'rice, mixed vegetables, soy sauce', 'Stir fry everything.', 'http://example2.com', 
         'test', '["rice", "vegetables", "soy sauce"]', 30, 2, 'Asian', '{}', 
         '{"rice": "grains", "mixed vegetables": "vegetables", "soy sauce": "condiments"}', 
         'medium', 'lunch', 0.9, 3)
    ]
    
    for recipe in test_recipes:
        conn.execute("""
        INSERT INTO recipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, recipe)
    
    conn.close()
    
    yield str(db_path)
    
    # Cleanup
    shutil.rmtree(temp_dir)

@pytest.fixture
def recipe_recommender(test_db_path):
    """Create a recipe recommender instance with the test database."""
    return EnhancedRecipeRecommender(test_db_path)

@pytest.fixture
def search_filters():
    """Create a default search filters object."""
    return SearchFilters()
