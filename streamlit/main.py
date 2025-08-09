"""
Main module for handling recipe search and model management
"""
import os
import sys
import pickle
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple
import time

# Add the parent directory to the path to access models
sys.path.append(str(Path(__file__).parent.parent))

from models.InvertedIndexSearch import InvertedIndexSearch

# Import from data directory - adjust path if running from streamlit directory
try:
    from data import load_dataset, get_available_datasets, DATA_DIR
except ImportError:
    # If running from streamlit directory, go up one level
    sys.path.append(str(Path(__file__).parent.parent))
    from data import load_dataset, get_available_datasets, DATA_DIR

class RecipeRecommender:
    """Main class for recipe recommendations"""
    
    def __init__(self):
        self.current_dataset = None
        self.current_model = None
        self.dataset_name = None
        self.is_trained = False
        
    def load_or_build_model(self, dataset_name: str, force_rebuild: bool = False):
        """Load pre-built model or build new one"""
        model_dir = Path(__file__).parent.parent / 'models'
        model_path = model_dir / f'inverted_index_model_{dataset_name}.pkl'
        
        # Check if we need to rebuild
        if not force_rebuild and model_path.exists() and not self._is_model_outdated(dataset_name, model_path):
            print(f"Loading pre-built model for {dataset_name}...")
            with open(model_path, 'rb') as f:
                self.current_model = pickle.load(f)
            self.dataset_name = dataset_name
            self.is_trained = True
            return "Model loaded successfully!"
        
        # Build new model
        print(f"Building new model for {dataset_name}...")
        
        # Load dataset
        try:
            df = load_dataset(dataset_name)
            self.current_dataset = df
        except Exception as e:
            return f"Error loading dataset: {str(e)}"
        
        # Initialize and build model
        self.current_model = InvertedIndexSearch()
        
        try:
            self.current_model.build_index(df)
            
            # Save the model
            model_dir = Path(__file__).parent.parent / 'models'
            model_dir.mkdir(exist_ok=True)
            with open(model_path, 'wb') as f:
                pickle.dump(self.current_model, f)
            
            # Save metadata
            metadata_path = model_dir / f'metadata_{dataset_name}.pkl'
            metadata = {
                'dataset_name': dataset_name,
                'build_time': time.time(),
                'recipe_count': len(df),
                'ingredient_count': len(self.current_model.inverted_index)
            }
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
            
            self.dataset_name = dataset_name
            self.is_trained = True
            return f"Model built successfully! Indexed {len(df):,} recipes with {len(self.current_model.inverted_index):,} unique ingredients."
            
        except Exception as e:
            return f"Error building model: {str(e)}"
    
    def _is_model_outdated(self, dataset_name: str, model_path: Path) -> bool:
        """Check if model needs to be rebuilt"""
        # Check if dataset file is newer than model
        dataset_path = DATA_DIR / get_available_datasets()[dataset_name]['file']
        
        if dataset_path.stat().st_mtime > model_path.stat().st_mtime:
            return True
        
        return False
    
    def search_recipes(self, ingredients: List[str], top_k: int = 10) -> List[Dict]:
        """Search for recipes matching the given ingredients"""
        if not self.is_trained or self.current_model is None:
            raise ValueError("Model not trained. Please select and load a dataset first.")
        
        # Clean ingredients
        ingredients = [ing.strip() for ing in ingredients if ing.strip()]
        
        if not ingredients:
            return []
        
        # Search using the model
        results = self.current_model.search(ingredients, top_k=top_k)
        
        # Format results for display
        formatted_results = []
        for recipe_id, recipe_data, score in results:
            formatted_results.append({
                'title': recipe_data['title'],
                'score': score,
                'matching_ingredients': len(set(ingredients).intersection(set(recipe_data['ingredients']))),
                'total_ingredients': recipe_data['ingredient_count'],
                'ingredients': recipe_data['ingredients'],
                'directions': recipe_data.get('directions', 'No directions available'),
                'is_vegetarian': recipe_data.get('is_vegetarian', False),
                'is_vegan': recipe_data.get('is_vegan', False)
            })
        
        return formatted_results
    
    def get_model_info(self) -> Dict:
        """Get information about the current model"""
        if not self.is_trained:
            return {'status': 'No model loaded'}
        
        model_dir = Path(__file__).parent.parent / 'models'
        metadata_path = model_dir / f'metadata_{self.dataset_name}.pkl'
        if metadata_path.exists():
            with open(metadata_path, 'rb') as f:
                metadata = pickle.load(f)
            return metadata
        
        return {
            'dataset_name': self.dataset_name,
            'recipe_count': len(self.current_model.recipe_data) if self.current_model else 0,
            'ingredient_count': len(self.current_model.inverted_index) if self.current_model else 0
        }