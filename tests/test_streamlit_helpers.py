"""Tests for streamlit helper functions."""

# Define the helper functions directly here to test them in isolation
def format_time(minutes):
    """Format time in minutes to readable format"""
    if not minutes:
        return "N/A"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}min"


def create_dietary_badges(recipe):
    """Create HTML for dietary badges"""
    badges = []
    if recipe.get("is_vegan"):
        badges.append('<span class="badge badge-vegan">🌱 Vegan</span>')
    elif recipe.get("is_vegetarian"):
        badges.append('<span class="badge badge-vegetarian">🥬 Vegetarian</span>')
    if recipe.get("is_gluten_free"):
        badges.append('<span class="badge badge-gluten-free">🌾 Gluten-Free</span>')
    if recipe.get("is_dairy_free"):
        badges.append('<span class="badge badge-dairy-free">🥛 Dairy-Free</span>')
    if recipe.get("is_nut_free"):
        badges.append('<span class="badge badge-nut-free">🥜 Nut-Free</span>')
    if recipe.get("is_low_carb"):
        badges.append('<span class="badge badge-low-carb">🍞 Low-Carb</span>')
    return " ".join(badges)


def create_nutritional_badges(recipe):
    """Create HTML for nutritional badges"""
    badges = []
    if recipe.get("is_high_protein"):
        badges.append('<span class="badge badge-high-protein">💪 High Protein</span>')
    if recipe.get("is_low_fat"):
        badges.append('<span class="badge badge-low-fat">🥗 Low Fat</span>')
    if recipe.get("is_high_fiber"):
        badges.append('<span class="badge badge-high-fiber">🌾 High Fiber</span>')
    return " ".join(badges)


def get_difficulty_icon(level):
    """Get difficulty icon and color"""
    if level == "easy":
        return "🟢 Easy"
    elif level == "medium":
        return "🟡 Medium"
    elif level == "hard":
        return "🔴 Hard"
    return "⚪ Unknown"


def get_meal_icon(meal_type):
    """Get meal type icon"""
    icons = {
        "breakfast": "🍳",
        "lunch": "🥪",
        "dinner": "🍽️",
        "dessert": "🍰",
        "snack": "🍿",
        "main": "🍛",
    }
    return icons.get(meal_type, "🍴")


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
        'is_vegetarian': False,
        'is_vegan': False,
        'is_gluten_free': False,
        'is_dairy_free': False,
        'is_nut_free': False
    }
    badges = streamlit_app.create_dietary_badges(recipe)
    assert badges == ""
    
    # Test with vegan (should show vegan, not vegetarian)
    recipe = {
        'is_vegan': True,
        'is_gluten_free': True,
        'is_dairy_free': True,
        'is_nut_free': True
    }
    badges = streamlit_app.create_dietary_badges(recipe)
    assert "Vegan" in badges
    assert "Gluten-Free" in badges
    assert "Dairy-Free" in badges
    assert "Nut-Free" in badges
    
    # Test with vegetarian only
    recipe = {
        'is_vegetarian': True,
        'is_vegan': False
    }
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
    recipe = {
        'is_high_protein': True,
        'is_low_fat': True,
        'is_high_fiber': True
    }
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
    
    # Test with main
    assert streamlit_app.get_meal_icon("main") == "🍛"
    
    # Test with unknown meal type
    assert streamlit_app.get_meal_icon("unknown") == "🍴"
