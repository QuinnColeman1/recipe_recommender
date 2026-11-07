"""UI tests: run the real Streamlit page against the small test database."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import recipe_app.main as main_module

APP = str(Path(__file__).parent.parent / "recipe_app" / "streamlit_app.py")


def _app(monkeypatch, db_path):
    monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", Path(db_path))
    # The page caches its recommender/stats; start every test fresh.
    st.cache_resource.clear()
    st.cache_data.clear()
    return AppTest.from_file(APP, default_timeout=60).run()


@pytest.fixture
def app(monkeypatch, test_db_path):
    at = _app(monkeypatch, test_db_path)
    assert not at.exception, [e.value for e in at.exception]
    return at


def button(at, text):
    return next(b for b in at.button if text in b.label)


def checkbox(at, label):
    return next(c for c in at.sidebar.checkbox if c.label == label)


def headers(at):
    return [h.value for h in at.main.header]


def recipe_titles(at):
    return [e.label for e in at.main.expander if e.label[:1].isdigit()]


def test_page_loads_with_database_stats(app):
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["📚 Total Recipes"] == "5"
    assert metrics["🌱 Vegan"] == "2"
    assert "Connected" in app.sidebar.success[0].value


def test_meal_type_options_include_new_types(app):
    meal = next(s for s in app.sidebar.selectbox if s.label == "Meal Type")
    assert meal.options[-3:] == ["🥗 Side", "🥤 Drink", "🍴 Other"]


def test_ingredient_search_shows_results(app):
    app.text_area[0].input("rice, soy sauce")
    button(app, "Search Recipes").click().run()
    assert "📋 Found 2 Recipes" in headers(app)
    titles = recipe_titles(app)
    assert any("Vegetable Stir Fry" in t for t in titles)
    assert any("Chicken Fried Rice" in t for t in titles)
    # matching ingredients are highlighted
    assert any(m.value.startswith("✅") for m in app.main.markdown)


def test_ingredient_search_with_apostrophe_and_exclusion(app):
    app.text_area[0].input("egg")
    app.text_area[1].input("peanut")
    button(app, "Search Recipes").click().run()
    titles = recipe_titles(app)
    assert len(titles) == 1 and "Chicken Fried Rice" in titles[0]

    app.text_area[0].input("confectioner's sugar")
    app.text_area[1].input("")
    button(app, "Search Recipes").click().run()
    assert any("Peanut Butter Cookies" in t for t in recipe_titles(app))


def test_empty_ingredient_search_warns(app):
    button(app, "Search Recipes").click().run()
    assert "Please enter at least one ingredient" in [w.value for w in app.warning]


def test_no_results_message(app):
    app.text_area[0].input("dragonfruit")
    button(app, "Search Recipes").click().run()
    assert any("No recipes found" in w.value for w in app.warning)


def test_save_recipe_keeps_results_and_saves(app):
    app.text_area[0].input("pasta")
    button(app, "Search Recipes").click().run()
    button(app, "Save Recipe").click().run()

    # Results are still on screen after the rerun caused by the Save click
    assert "📋 Found 1 Recipes" in headers(app)
    assert [r["title"] for r in app.session_state.saved_recipes] == [
        "Pasta with Tomato Sauce"
    ]

    # Saving twice doesn't duplicate
    button(app, "Save Recipe").click().run()
    assert len(app.session_state.saved_recipes) == 1

    remove = next(b for b in app.button if b.label == "Remove")
    remove.click().run()
    assert app.session_state.saved_recipes == []


def test_sidebar_filters_apply_to_browse(app):
    app.sidebar.radio[0].set_value("Browse All").run()
    checkbox(app, "Vegan").check().run()
    button(app, "Browse").click().run()
    titles = recipe_titles(app)
    assert len(titles) == 2
    assert all(("Pasta" in t) or ("Stir Fry" in t) for t in titles)


def test_text_search_applies_filters(app):
    app.sidebar.radio[0].set_value("Text Search").run()
    checkbox(app, "Gluten-Free").check().run()
    app.text_input[0].input("chicken")
    button(app, "🔍 Search").click().run()
    titles = recipe_titles(app)
    assert len(titles) == 1 and "Slow Roast Chicken" in titles[0]


def test_quick_meals_respects_time_limit(app):
    app.sidebar.radio[0].set_value("Quick Meals").run()
    button(app, "Find Quick Recipes").click().run()
    assert "Found 3 quick recipes under 30 minutes!" in [
        s.value for s in app.main.success
    ]
    assert not any("Slow Roast Chicken" in t for t in recipe_titles(app))


def test_results_are_kept_per_search_mode(app):
    app.text_area[0].input("pasta")
    button(app, "Search Recipes").click().run()
    app.sidebar.radio[0].set_value("Browse All").run()
    assert "📋 Found 1 Recipes" not in headers(app)  # not shown in another mode


def test_missing_database_shows_build_instructions(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path / "missing.db")
    assert not at.exception
    assert "Not connected" in at.sidebar.error[0].value
    assert "data.build_app_db" in at.sidebar.code[0].value


def match_slider(at):
    return next(
        s for s in at.slider if s.label.startswith("Minimum % of your ingredients")
    )


def test_match_slider_defaults_to_all_ingredients(app):
    assert match_slider(app).value == 100
    app.text_area[0].input("rice, soy sauce, chicken").run()
    assert "recipes must contain at least 3." in [c.value for c in app.main.caption][0]
    button(app, "Search Recipes").click().run()
    assert "📋 Found 1 Recipes" in headers(app)


def test_lower_match_slider_shows_partial_matches(app):
    app.text_area[0].input("rice, soy sauce, chicken")
    match_slider(app).set_value(50).run()
    assert any("at least 2." in c.value for c in app.main.caption)
    button(app, "Search Recipes").click().run()
    assert "📋 Found 2 Recipes" in headers(app)
    titles = recipe_titles(app)
    assert "Chicken Fried Rice" in titles[0]  # full match ranked first
    missing = [m.value for m in app.main.markdown if "Missing:" in m.value]
    assert missing == ["**❌ Missing:** chicken (2 of 3 of your ingredients)"]
    metrics = [m.value for m in app.main.metric if m.label == "Match"]
    assert metrics == ["100%", "67%"]
