"""Tests for streamlit helper functions."""

from recipe_app import ui_helpers as streamlit_app


def test_format_time():
    """Test the format_time function."""
    assert streamlit_app.format_time(30) == "30 min"
    assert streamlit_app.format_time(90) == "1h 30min"
    assert streamlit_app.format_time(120) == "2h"
    assert streamlit_app.format_time(145) == "2h 25min"
    assert streamlit_app.format_time(None) == "N/A"


def test_create_dietary_badges():
    """Test the create_dietary_badges function."""
    # Test with no dietary restrictions
    recipe = {
        "is_vegetarian": False,
        "is_vegan": False,
        "is_gluten_free": False,
        "is_dairy_free": False,
        "is_nut_free": False,
    }
    badges = streamlit_app.create_dietary_badges(recipe)
    assert badges == ""

    # Test with vegan (should show vegan, not vegetarian)
    recipe = {
        "is_vegan": True,
        "is_gluten_free": True,
        "is_dairy_free": True,
        "is_nut_free": True,
    }
    badges = streamlit_app.create_dietary_badges(recipe)
    assert "Vegan" in badges
    assert "Gluten-Free" in badges
    assert "Dairy-Free" in badges
    assert "Nut-Free" in badges

    # Test with vegetarian only
    recipe = {"is_vegetarian": True, "is_vegan": False}
    badges = streamlit_app.create_dietary_badges(recipe)
    assert "Vegetarian" in badges
    assert "Vegan" not in badges


def test_create_nutritional_badges():
    """Test the create_nutritional_badges function."""
    # Test with no nutrition data
    recipe = {}
    badges = streamlit_app.create_nutritional_badges(recipe)
    assert badges == ""

    # Test with nutrition data
    recipe = {"is_high_protein": True, "is_low_fat": True, "is_high_fiber": True}
    badges = streamlit_app.create_nutritional_badges(recipe)
    assert "High Protein" in badges
    assert "Low Fat" in badges
    assert "High Fiber" in badges


def test_get_difficulty_icon():
    """Test the get_difficulty_icon function."""
    # Test with easy difficulty
    result = streamlit_app.get_difficulty_icon("easy")
    assert result == "🟢 Easy"

    # Test with medium difficulty
    result = streamlit_app.get_difficulty_icon("medium")
    assert result == "🟡 Medium"

    # Test with hard difficulty
    result = streamlit_app.get_difficulty_icon("hard")
    assert result == "🔴 Hard"

    # Test with unknown difficulty
    result = streamlit_app.get_difficulty_icon("unknown")
    assert result == "⚪ Unknown"


def test_get_meal_icon():
    """Test the get_meal_icon function."""
    # Test with breakfast
    assert streamlit_app.get_meal_icon("breakfast") == "🍳"

    # Test with lunch
    assert streamlit_app.get_meal_icon("lunch") == "🥪"

    # Test with dinner
    assert streamlit_app.get_meal_icon("dinner") == "🍽️"

    # Test with dessert
    assert streamlit_app.get_meal_icon("dessert") == "🍰"

    # Test with snack
    assert streamlit_app.get_meal_icon("snack") == "🍿"

    # Test with the newer meal types
    assert streamlit_app.get_meal_icon("side") == "🥗"
    assert streamlit_app.get_meal_icon("drink") == "🥤"

    # Test with unknown meal type
    assert streamlit_app.get_meal_icon("unknown") == "🍴"


def test_format_directions():
    assert streamlit_app.format_directions("Mix.\nBake.") == "1. Mix.\n2. Bake."
    assert streamlit_app.format_directions("Just stir") == "Just stir"
    assert streamlit_app.format_directions(None) == ""


def test_format_ingredient_and_escaping():
    assert streamlit_app.format_ingredient("sugar", "3/4 c.") == "3/4 c. sugar"
    assert streamlit_app.format_ingredient("salt") == "salt"
    assert streamlit_app.escape_markdown("a*b_c") == "a\\*b\\_c"
