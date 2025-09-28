"""
Enhanced Streamlit Recipe Recommender Application
"""

import streamlit as st

# Import from the streamlit package
from streamlit.main import (
    EnhancedRecipeRecommender,
    SearchFilters,
    MealType,
    DifficultyLevel,
    SortBy,
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

# Initialize session state
if "recommender" not in st.session_state:
    st.session_state.recommender = EnhancedRecipeRecommender()

if "search_mode" not in st.session_state:
    st.session_state.search_mode = "ingredients"

if "saved_recipes" not in st.session_state:
    st.session_state.saved_recipes = []

if "pantry_items" not in st.session_state:
    st.session_state.pantry_items = []


# Helper functions
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
            f"{idx}. {get_meal_icon(recipe.get('meal_type', ''))} **{recipe['title']}** "
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

            # Time breakdown
            if recipe.get("prep_time") or recipe.get("cook_time"):
                st.markdown(
                    f"**⏱️ Time:** Prep: {format_time(recipe.get('prep_time'))} | "
                    f"Cook: {format_time(recipe.get('cook_time'))}"
                )

            # Ingredients
            st.markdown("### 📝 Ingredients")

            # Organize ingredients by category if available
            if recipe.get("ingredient_categories") and recipe.get("ingredients_clean"):
                categories = {}
                for ing, cat in zip(
                    recipe["ingredients_clean"], recipe["ingredient_categories"]
                ):
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(ing)

                # Display by category
                cols = st.columns(min(3, len(categories)))
                for cat_idx, (cat, ings) in enumerate(categories.items()):
                    with cols[cat_idx % 3]:
                        st.markdown(f"**{cat.title()}**")
                        for ing in ings:
                            # Highlight matching ingredients
                            if search_ingredients and any(
                                s in ing for s in search_ingredients
                            ):
                                st.markdown(f"✅ **{ing}**")
                            else:
                                st.markdown(f"• {ing}")
            else:
                # Simple ingredient list
                ingredients_list = recipe.get("ingredients_clean", [])
                if ingredients_list:
                    cols = st.columns(2)
                    mid_point = len(ingredients_list) // 2

                    with cols[0]:
                        for ing in ingredients_list[:mid_point]:
                            if search_ingredients and any(
                                s in ing for s in search_ingredients
                            ):
                                st.markdown(f"✅ **{ing}**")
                            else:
                                st.markdown(f"• {ing}")

                    with cols[1]:
                        for ing in ingredients_list[mid_point:]:
                            if search_ingredients and any(
                                s in ing for s in search_ingredients
                            ):
                                st.markdown(f"✅ **{ing}**")
                            else:
                                st.markdown(f"• {ing}")
                else:
                    st.info("No ingredient list available")

            # Directions
            if recipe.get("directions"):
                st.markdown("### 📖 Directions")
                st.write(recipe["directions"])

            # Action buttons
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button(
                    "💾 Save Recipe", key=f"save_{recipe.get('recipe_id', idx)}"
                ):
                    if recipe not in st.session_state.saved_recipes:
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
    if st.session_state.recommender.is_connected:
        st.success("✅ Connected to Recipe Database")
        stats = st.session_state.recommender.get_database_stats()
        st.metric("Total Recipes", f"{stats.get('total_recipes', 0):,}")
    else:
        st.error("❌ Not connected to database")
        st.info("Please ensure the recipes.db file exists in the data folder")

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
            ["Any", "Breakfast", "Lunch", "Dinner", "Dessert", "Snack", "Main"],
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
if st.session_state.recommender.is_connected:
    stats = st.session_state.recommender.get_database_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📚 Total Recipes", f"{stats.get('total_recipes', 0):,}")
    with col2:
        st.metric("🥬 Vegetarian", f"{stats.get('vegetarian_count', 0):,}")
    with col3:
        st.metric("🌱 Vegan", f"{stats.get('vegan_count', 0):,}")
    with col4:
        st.metric("🌾 Gluten-Free", f"{stats.get('gluten_free_count', 0):,}")

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

    num_results = st.slider("Number of results", 5, 50, 10)

    if st.button("🔍 Search Recipes", type="primary", use_container_width=True):
        if ingredients_input.strip():
            # Parse ingredients
            if "," in ingredients_input:
                ingredients = [
                    ing.strip() for ing in ingredients_input.split(",") if ing.strip()
                ]
            else:
                ingredients = [
                    ing.strip() for ing in ingredients_input.split("\n") if ing.strip()
                ]

            # Parse exclusions
            if exclude_input.strip():
                if "," in exclude_input:
                    exclusions = [
                        ing.strip() for ing in exclude_input.split(",") if ing.strip()
                    ]
                else:
                    exclusions = [
                        ing.strip() for ing in exclude_input.split("\n") if ing.strip()
                    ]
                filters.exclude_ingredients = exclusions

            with st.spinner("Searching for recipes..."):
                results = st.session_state.recommender.search_by_ingredients(
                    ingredients, filters, sort_option, num_results
                )

                if results:
                    display_results(results, ingredients)
                else:
                    st.warning(
                        "No recipes found matching your criteria. Try adjusting filters."
                    )
        else:
            st.warning("Please enter at least one ingredient")

elif search_mode == "Text Search":
    st.header("📝 Text Search")

    search_query = st.text_input(
        "Search for recipes by name or description",
        placeholder="chocolate cake, pasta carbonara, thai curry...",
    )

    num_results = st.slider("Number of results", 5, 50, 10)

    if st.button("🔍 Search", type="primary", use_container_width=True):
        if search_query.strip():
            with st.spinner("Searching..."):
                results = st.session_state.recommender.search_by_text(
                    search_query, filters, sort_option, num_results
                )

                if results:
                    display_results(results)
                else:
                    st.warning("No recipes found. Try different search terms.")
        else:
            st.warning("Please enter a search query")

elif search_mode == "Browse All":
    st.header("📚 Browse Recipes")

    num_results = st.slider("Number of results", 10, 100, 20)

    if st.button("📖 Browse", type="primary", use_container_width=True):
        with st.spinner("Loading recipes..."):
            results = st.session_state.recommender.browse_recipes(
                filters, sort_option, num_results
            )

            if results:
                display_results(results)
            else:
                st.warning("No recipes found matching your filters.")

elif search_mode == "Quick Meals":
    st.header("⏱️ Quick Meals")

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
            results = st.session_state.recommender.get_quick_recipes(
                quick_time, num_results
            )

            if results:
                st.success(
                    f"Found {len(results)} quick recipes under {quick_time} minutes!"
                )
                display_results(results)
            else:
                st.warning("No quick recipes found. Try increasing the time limit.")

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
