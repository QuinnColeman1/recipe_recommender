"""
Enhanced Streamlit Recipe Recommender Application
"""

import sys
from pathlib import Path

import streamlit as st

# `streamlit run recipe_app/streamlit_app.py` puts only recipe_app/ on the path;
# add the project root so the recipe_app package can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recipe_app.main import (  # noqa: E402
    EnhancedRecipeRecommender,
    SearchFilters,
    MealType,
    DifficultyLevel,
    SortBy,
    min_matches_needed,
)
from recipe_app.ui_helpers import (  # noqa: E402
    format_time,
    create_dietary_badges,
    create_nutritional_badges,
    get_difficulty_icon,
    get_meal_icon,
    escape_markdown,
    format_ingredient,
    format_directions,
)

# Page configuration
st.set_page_config(
    page_title="Recipe Finder Pro",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling
st.markdown(
    """
<style>
    .recipe-card {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f8f9fa;
        margin-bottom: 1rem;
    }
    .badge {
        display: inline-block;
        padding: 0.25rem 0.5rem;
        margin: 0.2rem;
        border-radius: 0.25rem;
        font-size: 0.85rem;
        font-weight: 500;
    }
    .badge-vegan { background-color: #28a745; color: white; }
    .badge-vegetarian { background-color: #5cb85c; color: white; }
    .badge-gluten-free { background-color: #f0ad4e; color: white; }
    .badge-dairy-free { background-color: #5bc0de; color: white; }
    .badge-nut-free { background-color: #d9534f; color: white; }
    .badge-low-carb { background-color: #777; color: white; }
    .badge-high-protein { background-color: #ff6b6b; color: white; }
    .badge-low-fat { background-color: #4ecdc4; color: white; }
    .badge-high-fiber { background-color: #95e77e; color: white; }
    .time-badge { background-color: #e9ecef; color: #495057; }
    .difficulty-easy { color: #28a745; }
    .difficulty-medium { color: #ffc107; }
    .difficulty-hard { color: #dc3545; }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_recommender() -> EnhancedRecipeRecommender:
    """One read-only database connection shared by every browser session."""
    return EnhancedRecipeRecommender()


@st.cache_data(show_spinner=False)
def get_stats(db_path: str) -> dict:
    """Whole-database stats; computed once, not on every click."""
    return get_recommender().get_database_stats()


recommender = get_recommender()
stats = get_stats(recommender.db_path) if recommender.is_connected else {}

# Initialize session state
if "saved_recipes" not in st.session_state:
    st.session_state.saved_recipes = []

# Last search results, kept so buttons inside results (e.g. Save) still work
# after Streamlit reruns the script.
if "last_results" not in st.session_state:
    st.session_state.last_results = None

if "pantry_items" not in st.session_state:
    st.session_state.pantry_items = []


def display_results(results, search_ingredients=None):
    """Display search results with rich formatting"""
    st.header(f"📋 Found {len(results)} Recipes")

    # Results summary stats
    if len(results) > 0:
        col1, col2, col3 = st.columns(3)
        with col1:
            time_recipes = [r for r in results if r.get("total_time")]
            if time_recipes:
                avg_time = sum(r["total_time"] for r in time_recipes) / len(
                    time_recipes
                )
                st.metric("⏱️ Avg Time", format_time(int(avg_time)))
            else:
                st.metric("⏱️ Avg Time", "N/A")
        with col2:
            avg_ingredients = sum(r["ingredient_count"] for r in results) / len(results)
            st.metric("🥘 Avg Ingredients", f"{avg_ingredients:.1f}")
        with col3:
            vegetarian_count = sum(1 for r in results if r.get("is_vegetarian"))
            st.metric("🥬 Vegetarian Options", vegetarian_count)

    # Display each recipe
    for idx, recipe in enumerate(results, 1):
        with st.expander(
            f"{idx}. {get_meal_icon(recipe.get('meal_type', ''))} **{escape_markdown(recipe['title'])}** "
            f"({get_difficulty_icon(recipe.get('difficulty_level', ''))})",
            expanded=(idx <= 3),  # Expand first 3 results
        ):
            # Top metrics row
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if recipe.get("match_percentage") is not None:
                    st.metric("Match", f"{recipe['match_percentage']:.0f}%")
                else:
                    st.metric("Quality", f"{recipe.get('quality_score', 0):.1f}")
            with col2:
                st.metric("Time", format_time(recipe.get("total_time")))
            with col3:
                st.metric("Servings", recipe.get("servings", "N/A"))
            with col4:
                st.metric("Ingredients", recipe["ingredient_count"])

            # Dietary and nutritional badges
            dietary_badges = create_dietary_badges(recipe)
            nutritional_badges = create_nutritional_badges(recipe)

            if dietary_badges or nutritional_badges:
                st.markdown(
                    dietary_badges + " " + nutritional_badges, unsafe_allow_html=True
                )

            # Which of the searched ingredients this recipe doesn't use
            if recipe.get("missing_ingredients"):
                missing = ", ".join(recipe["missing_ingredients"])
                st.markdown(
                    f"**❌ Missing:** {escape_markdown(missing)} "
                    f"({recipe['matching_ingredients']} of "
                    f"{recipe['matching_ingredients'] + len(recipe['missing_ingredients'])} "
                    "of your ingredients)"
                )

            # Time breakdown
            if recipe.get("prep_time") or recipe.get("cook_time"):
                st.markdown(
                    f"**⏱️ Time:** Prep: {format_time(recipe.get('prep_time'))} | "
                    f"Cook: {format_time(recipe.get('cook_time'))}"
                )

            # Ingredients, grouped by category, with amounts when known
            st.markdown("### 📝 Ingredients")
            names = recipe.get("ingredients_clean") or []
            categories = recipe.get("ingredient_categories") or []
            quantities = recipe.get("ingredient_quantities") or []
            if len(categories) != len(names):
                categories = ["ingredients"] * len(names)
            if len(quantities) != len(names):
                quantities = [None] * len(names)

            if names:
                groups = {}
                for name, cat, qty in zip(names, categories, quantities):
                    groups.setdefault(cat, []).append((name, qty))
                cols = st.columns(min(3, len(groups)))
                for cat_idx, (cat, items) in enumerate(groups.items()):
                    with cols[cat_idx % len(cols)]:
                        st.markdown(f"**{cat.replace('_', ' ').title()}**")
                        for name, qty in items:
                            label = escape_markdown(format_ingredient(name, qty))
                            if search_ingredients and any(
                                s in name for s in search_ingredients
                            ):
                                st.markdown(f"✅ **{label}**")
                            else:
                                st.markdown(f"• {label}")
            else:
                st.info("No ingredient list available")

            # Directions
            if recipe.get("directions"):
                st.markdown("### 📖 Directions")
                st.markdown(format_directions(recipe["directions"]))
            if recipe.get("link"):
                st.markdown(f"[🔗 Original recipe]({recipe['link']})")

            # Action buttons
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(
                    "💾 Save Recipe", key=f"save_{recipe.get('recipe_id', idx)}"
                ):
                    saved_ids = {
                        r.get("recipe_id") for r in st.session_state.saved_recipes
                    }
                    if recipe.get("recipe_id") not in saved_ids:
                        st.session_state.saved_recipes.append(recipe)
                    st.success("Recipe saved!")
            with col2:
                if st.button(
                    "🛒 Shopping List", key=f"shop_{recipe.get('recipe_id', idx)}"
                ):
                    st.info("Shopping list feature coming soon!")
            with col3:
                if st.button("📤 Share", key=f"share_{recipe.get('recipe_id', idx)}"):
                    st.info("Share feature coming soon!")


# Sidebar
with st.sidebar:
    st.header("🔧 Search & Filter Options")

    # Database connection status
    if recommender.is_connected:
        st.success("✅ Connected to Recipe Database")
        st.metric("Total Recipes", f"{stats.get('total_recipes', 0):,}")
    else:
        st.error("❌ Not connected to database")
        st.info(recommender.connection_error or "Database unavailable")
        st.code("poetry run python -m data.build_app_db", language="bash")

    # Search Mode Selection
    st.subheader("🔍 Search Mode")
    search_mode = st.radio(
        "Choose search method:",
        ["Ingredient Search", "Text Search", "Browse All", "Quick Meals"],
        key="search_mode_radio",
    )

    # Filters Section
    with st.expander("🥗 Dietary Restrictions", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            is_vegetarian = st.checkbox("Vegetarian")
            is_vegan = st.checkbox("Vegan")
            is_gluten_free = st.checkbox("Gluten-Free")
        with col2:
            is_dairy_free = st.checkbox("Dairy-Free")
            is_nut_free = st.checkbox("Nut-Free")
            is_low_carb = st.checkbox("Low-Carb")

    with st.expander("💪 Nutritional Preferences"):
        col1, col2 = st.columns(2)
        with col1:
            is_high_protein = st.checkbox("High Protein")
            is_low_fat = st.checkbox("Low Fat")
        with col2:
            is_high_fiber = st.checkbox("High Fiber")

    with st.expander("⏱️ Time Constraints"):
        max_total_time = st.slider(
            "Max Total Time (minutes)",
            min_value=0,
            max_value=180,
            value=0,
            step=15,
            help="Set to 0 for no limit",
        )
        if max_total_time == 0:
            max_total_time = None

    with st.expander("🍴 Meal & Difficulty"):
        meal_type = st.selectbox(
            "Meal Type",
            [
                "Any",
                "Breakfast",
                "Lunch",
                "Dinner",
                "Dessert",
                "Snack",
                "Side",
                "Drink",
                "Other",
            ],
            format_func=lambda x: f"{get_meal_icon(x.lower())} {x}"
            if x != "Any"
            else "Any",
        )

        difficulty = st.selectbox(
            "Difficulty Level",
            ["Any", "Easy", "Medium", "Hard"],
            format_func=lambda x: get_difficulty_icon(x.lower())
            if x != "Any"
            else "Any",
        )

    with st.expander("📊 Quality & Sorting"):
        min_quality = st.slider(
            "Minimum Quality Score", min_value=0.0, max_value=1.0, value=0.5, step=0.1
        )

        sort_by = st.selectbox(
            "Sort Results By",
            [
                "Relevance",
                "Cooking Time",
                "Quality Score",
                "Ingredient Count",
                "Difficulty",
            ],
            help="Choose how to order search results",
        )

    # Create filters object
    filters = SearchFilters(
        is_vegetarian=is_vegetarian if is_vegetarian else None,
        is_vegan=is_vegan if is_vegan else None,
        is_gluten_free=is_gluten_free if is_gluten_free else None,
        is_dairy_free=is_dairy_free if is_dairy_free else None,
        is_nut_free=is_nut_free if is_nut_free else None,
        is_low_carb=is_low_carb if is_low_carb else None,
        is_high_protein=is_high_protein if is_high_protein else None,
        is_low_fat=is_low_fat if is_low_fat else None,
        is_high_fiber=is_high_fiber if is_high_fiber else None,
        max_total_time=max_total_time,
        meal_type=MealType[meal_type.upper()],
        difficulty_level=DifficultyLevel[difficulty.upper()],
        min_quality_score=min_quality,
    )

    # Sort by mapping
    sort_mapping = {
        "Relevance": SortBy.RELEVANCE,
        "Cooking Time": SortBy.TIME,
        "Quality Score": SortBy.QUALITY,
        "Ingredient Count": SortBy.INGREDIENTS,
        "Difficulty": SortBy.DIFFICULTY,
    }
    sort_option = sort_mapping.get(sort_by, SortBy.RELEVANCE)

# Main content area
st.title("🍳 Recipe Finder Pro")
st.markdown(
    "*Discover delicious recipes based on ingredients, dietary preferences, and time constraints*"
)

# Quick Stats
if recommender.is_connected:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📚 Total Recipes", f"{stats.get('total_recipes', 0):,}")
    with col2:
        st.metric("🥬 Vegetarian", f"{stats.get('vegetarian_count', 0):,}")
    with col3:
        st.metric("🌱 Vegan", f"{stats.get('vegan_count', 0):,}")
    with col4:
        st.metric("🌾 Gluten-Free", f"{stats.get('gluten_free_count', 0):,}")


def parse_ingredient_list(text):
    """Split comma-separated or one-per-line input into a clean list."""
    separator = "," if "," in text else "\n"
    return [item.strip() for item in text.split(separator) if item.strip()]


def remember_results(results, empty_message, ingredients=None, success_message=None):
    """Store results so they survive the reruns caused by buttons inside them."""
    st.session_state.last_results = {
        "mode": search_mode,
        "results": results,
        "ingredients": ingredients,
        "empty_message": empty_message,
        "success_message": success_message,
    }


# Search Interface
if search_mode == "Ingredient Search":
    st.header("🥘 Search by Ingredients")

    col1, col2 = st.columns([3, 1])
    with col1:
        ingredients_input = st.text_area(
            "Enter ingredients (one per line or comma-separated)",
            height=100,
            placeholder="tomatoes\nbasil\nmozzarella\nor: tomatoes, basil, mozzarella",
            help="Enter the ingredients you have available",
        )

    with col2:
        st.write("")  # Spacer
        exclude_input = st.text_area(
            "Exclude ingredients",
            height=100,
            placeholder="nuts\npeanuts",
            help="Enter ingredients to exclude",
        )

    min_match_percent = st.slider(
        "Minimum % of your ingredients each recipe must use",
        min_value=10,
        max_value=100,
        value=100,
        step=10,
        help="100% = recipes must contain every ingredient you entered. "
        "Lower it to also see recipes that use most of them.",
    )
    typed = parse_ingredient_list(ingredients_input)
    if typed:
        needed = min_matches_needed(len(typed), min_match_percent)
        st.caption(
            f"With {len(typed)} ingredient{'s' if len(typed) != 1 else ''}, "
            f"recipes must contain at least {needed}."
        )

    num_results = st.slider("Number of results", 5, 50, 10)

    if st.button("🔍 Search Recipes", type="primary", use_container_width=True):
        ingredients = typed
        if ingredients:
            filters.exclude_ingredients = parse_ingredient_list(exclude_input)
            with st.spinner("Searching for recipes..."):
                results = recommender.search_by_ingredients(
                    ingredients,
                    filters,
                    sort_option,
                    num_results,
                    min_match_percent=min_match_percent,
                )
            remember_results(
                results,
                "No recipes found matching your criteria. Try adjusting filters.",
                ingredients=[ing.lower() for ing in ingredients],
            )
        else:
            st.session_state.last_results = None
            st.warning("Please enter at least one ingredient")

elif search_mode == "Text Search":
    st.header("📝 Text Search")

    search_query = st.text_input(
        "Search for recipes by name or ingredient",
        placeholder="chocolate cake, pasta carbonara, thai curry...",
    )

    num_results = st.slider("Number of results", 5, 50, 10)

    if st.button("🔍 Search", type="primary", use_container_width=True):
        if search_query.strip():
            with st.spinner("Searching..."):
                results = recommender.search_by_text(
                    search_query, filters, sort_option, num_results
                )
            remember_results(results, "No recipes found. Try different search terms.")
        else:
            st.session_state.last_results = None
            st.warning("Please enter a search query")

elif search_mode == "Browse All":
    st.header("📚 Browse Recipes")

    num_results = st.slider("Number of results", 10, 100, 20)

    if st.button("📖 Browse", type="primary", use_container_width=True):
        with st.spinner("Loading recipes..."):
            results = recommender.browse_recipes(filters, sort_option, num_results)
        remember_results(results, "No recipes found matching your filters.")

elif search_mode == "Quick Meals":
    st.header("⏱️ Quick Meals")
    st.caption(
        "Times are estimated from the durations written in each recipe's directions; "
        "recipes that don't mention any time can't appear here."
    )

    quick_time = st.slider(
        "Maximum cooking time (minutes)",
        15,
        60,
        30,
        5,
        help="Find recipes that can be made quickly",
    )

    num_results = st.slider("Number of results", 5, 30, 10)

    if st.button("⚡ Find Quick Recipes", type="primary", use_container_width=True):
        with st.spinner("Finding quick recipes..."):
            results = recommender.get_quick_recipes(quick_time, num_results, filters)
        remember_results(
            results,
            "No quick recipes found. Try increasing the time limit or loosening filters.",
            success_message=f"Found {len(results)} quick recipes under {quick_time} minutes!",
        )

# Show the latest results for the current mode (also after Save/Remove clicks)
last = st.session_state.last_results
if last and last["mode"] == search_mode:
    if last["results"]:
        if last["success_message"]:
            st.success(last["success_message"])
        display_results(last["results"], last["ingredients"])
    else:
        st.warning(last["empty_message"])

# Saved Recipes Section
if st.session_state.saved_recipes:
    with st.expander(f"💾 Saved Recipes ({len(st.session_state.saved_recipes)})"):
        for idx, recipe in enumerate(st.session_state.saved_recipes):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"{idx + 1}. {recipe['title']}")
            with col2:
                if st.button("Remove", key=f"remove_saved_{idx}"):
                    st.session_state.saved_recipes.pop(idx)
                    st.rerun()

# Footer
st.divider()
st.caption("Recipe Finder Pro - Your intelligent cooking companion 👨‍🍳")
st.caption(
    "Filter by dietary needs, time constraints, and nutritional preferences to find your perfect meal!"
)
