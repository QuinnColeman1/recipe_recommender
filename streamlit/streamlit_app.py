"""
Streamlit Recipe Recommender Application
"""
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# Add parent directory to path to access models and data
sys.path.append(str(Path(__file__).parent.parent))

from main import RecipeRecommender
from data import get_available_datasets

# Page configuration
st.set_page_config(
    page_title="Recipe Recommender",
    page_icon="🍳",
    layout="wide"
)

# Initialize session state
if 'recommender' not in st.session_state:
    st.session_state.recommender = RecipeRecommender()

if 'selected_dataset' not in st.session_state:
    st.session_state.selected_dataset = None

if 'ingredients_input' not in st.session_state:
    st.session_state.ingredients_input = ""

# Title and description
st.title("🍳 Recipe Recommender")
st.markdown("Find recipes based on the ingredients you have!")

# Sidebar for dataset selection
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Get available datasets
    available_datasets = get_available_datasets()
    
    if not available_datasets:
        st.error("No datasets found! Please ensure .pkl files are in the data folder.")
    else:
        # Dataset selection
        dataset_options = {k: v['name'] for k, v in available_datasets.items()}
        selected_dataset = st.selectbox(
            "Select Recipe Dataset",
            options=list(dataset_options.keys()),
            format_func=lambda x: dataset_options[x],
            help="Choose which recipe collection to search from"
        )
        
        # Show dataset description
        if selected_dataset:
            st.info(available_datasets[selected_dataset]['description'])
        
        # Load/Build model button
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Load Model", type="primary", use_container_width=True):
                with st.spinner("Loading model..."):
                    result = st.session_state.recommender.load_or_build_model(selected_dataset)
                    st.success(result)
                    st.session_state.selected_dataset = selected_dataset
        
        with col2:
            if st.button("Rebuild Model", use_container_width=True):
                with st.spinner("Rebuilding model..."):
                    result = st.session_state.recommender.load_or_build_model(selected_dataset, force_rebuild=True)
                    st.success(result)
                    st.session_state.selected_dataset = selected_dataset
        
        # Model info
        if st.session_state.recommender.is_trained:
            st.divider()
            st.subheader("📊 Model Information")
            model_info = st.session_state.recommender.get_model_info()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Recipes", f"{model_info.get('recipe_count', 0):,}")
            with col2:
                st.metric("Unique Ingredients", f"{model_info.get('ingredient_count', 0):,}")

# Main content
if st.session_state.recommender.is_trained:
    # Search section
    st.header("🔍 Search Recipes")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Ingredients input
        ingredients_input = st.text_area(
            "Enter your ingredients (one per line or comma-separated)",
            value=st.session_state.ingredients_input,
            height=100,
            placeholder="Example:\ntomatoes\nbasil\nmozzarella\nor: tomatoes, basil, mozzarella"
        )
        st.session_state.ingredients_input = ingredients_input
    
    with col2:
        st.write("") # Empty space for alignment
        st.write("") # Empty space for alignment
        num_results = st.slider("Number of results", min_value=5, max_value=50, value=10)
    
    # Search button
    if st.button("🔍 Find Recipes", type="primary", use_container_width=True):
        if ingredients_input.strip():
            # Parse ingredients
            if ',' in ingredients_input:
                ingredients = [ing.strip() for ing in ingredients_input.split(',')]
            else:
                ingredients = [ing.strip() for ing in ingredients_input.split('\n')]
            
            # Remove empty strings
            ingredients = [ing for ing in ingredients if ing]
            
            if ingredients:
                with st.spinner("Searching for recipes..."):
                    try:
                        results = st.session_state.recommender.search_recipes(ingredients, top_k=num_results)
                        
                        if results:
                            st.success(f"Found {len(results)} recipes matching your ingredients!")
                            
                            # Display results
                            st.header("📋 Recipe Results")
                            
                            for idx, recipe in enumerate(results, 1):
                                with st.expander(
                                    f"{idx}. {recipe['title']} "
                                    f"(Match: {recipe['matching_ingredients']}/{len(ingredients)} ingredients, "
                                    f"Score: {recipe['score']:.2%})"
                                ):
                                    col1, col2 = st.columns([2, 1])
                                    
                                    with col1:
                                        st.subheader("Ingredients")
                                        # Highlight matching ingredients
                                        ingredient_list = []
                                        for ing in recipe['ingredients']:
                                            if ing.lower() in [i.lower() for i in ingredients]:
                                                ingredient_list.append(f"✅ **{ing}**")
                                            else:
                                                ingredient_list.append(f"• {ing}")
                                        st.write("\n".join(ingredient_list))
                                    
                                    with col2:
                                        st.subheader("Recipe Info")
                                        st.write(f"**Total Ingredients:** {recipe['total_ingredients']}")
                                        st.write(f"**Match Score:** {recipe['score']:.2%}")
                                        
                                        tags = []
                                        if recipe.get('is_vegetarian'):
                                            tags.append("🥬 Vegetarian")
                                        if recipe.get('is_vegan'):
                                            tags.append("🌱 Vegan")
                                        
                                        if tags:
                                            st.write("**Tags:** " + ", ".join(tags))
                                    
                                    if recipe.get('directions'):
                                        st.subheader("Directions")
                                        st.write(recipe['directions'])
                        else:
                            st.warning("No recipes found matching your ingredients. Try different ingredients!")
                            
                    except Exception as e:
                        st.error(f"Error searching recipes: {str(e)}")
            else:
                st.warning("Please enter at least one ingredient!")
        else:
            st.warning("Please enter some ingredients to search!")

else:
    # Show instructions if no model is loaded
    st.info("👈 Please select a dataset and load the model from the sidebar to begin searching for recipes.")
    
    # Quick start guide
    with st.expander("🚀 Quick Start Guide"):
        st.markdown("""
        1. **Select a Dataset**: Choose from the available recipe collections in the sidebar
        2. **Load the Model**: Click the 'Load Model' button to prepare the search engine
        3. **Enter Ingredients**: Type the ingredients you have available
        4. **Search**: Click 'Find Recipes' to get personalized recommendations
        
        **Tips:**
        - Enter ingredients one per line or comma-separated
        - The more ingredients you enter, the more specific the results
        - Use the 'Rebuild Model' button if you've updated the dataset files
        """)

# Footer
st.divider()
st.caption("Recipe Recommender - Find delicious recipes based on what you have in your kitchen! 🍽️")