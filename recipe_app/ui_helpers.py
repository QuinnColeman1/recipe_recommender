"""Pure formatting helpers for the Streamlit UI (no Streamlit import, easy to test)."""

import re

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_#|<>\[\]])")


def escape_markdown(text):
    """Escape characters that would turn recipe text into Markdown formatting."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


def format_ingredient(name, quantity=None):
    """'sugar' + '3/4 c.' -> '3/4 c. sugar'."""
    return f"{quantity} {name}" if quantity else name


def format_directions(directions):
    """Newline-separated steps -> a numbered Markdown list."""
    steps = [step.strip() for step in str(directions or "").split("\n") if step.strip()]
    if len(steps) <= 1:
        return escape_markdown(steps[0]) if steps else ""
    return "\n".join(f"{i}. {escape_markdown(step)}" for i, step in enumerate(steps, 1))


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
        "side": "🥗",
        "drink": "🥤",
        "other": "🍴",
    }
    return icons.get(meal_type, "🍴")
