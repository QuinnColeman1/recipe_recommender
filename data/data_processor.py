import duckdb
import pandas as pd
import re
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

class SimpleRecipeProcessor:
    def __init__(self, db_path='recipes.db'):
        """Initialize with DuckDB only - no ML dependencies"""
        self.con = duckdb.connect(db_path)
        
        # Define ingredient blacklists for dietary classification
        self.meat_keywords = [
            'chicken', 'beef', 'pork', 'lamb', 'turkey', 'duck', 'meat', 'poultry',
            'bacon', 'ham', 'sausage', 'pepperoni', 'salami', 'prosciutto',
            'fish', 'salmon', 'tuna', 'shrimp', 'crab', 'lobster', 'seafood',
            'steak', 'ribs', 'wings', 'ground beef', 'hamburger'
        ]
        
        self.dairy_egg_keywords = [
            'milk', 'cream', 'cheese', 'butter', 'yogurt', 'eggs', 'egg',
            'cheddar', 'mozzarella', 'parmesan', 'mayo', 'mayonnaise',
            'ice cream', 'cottage cheese', 'sour cream'
        ]
        
        self.dessert_keywords = [
            'cake', 'cookie', 'brownie', 'pie', 'chocolate', 'sugar',
            'dessert', 'sweet', 'frosting', 'icing', 'candy', 'syrup'
        ]
        
        # Initialize database
        self.setup_database()
    
    def setup_database(self):
        """Setup DuckDB with simplified schema"""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                recipe_id INTEGER PRIMARY KEY,
                title VARCHAR,
                ingredients TEXT,
                directions TEXT,
                rating FLOAT,
                cooking_time INTEGER,
                cuisine_type VARCHAR,
                -- Processed fields
                ingredients_clean TEXT[],
                ingredient_count INTEGER,
                is_vegetarian BOOLEAN,
                is_vegan BOOLEAN,
                is_dessert BOOLEAN
            )
        """)
    
    def load_data_from_csv(self, csv_path):
        """Load CSV data into DuckDB"""
        print(f"Loading data from {csv_path}...")
        
        # Use DuckDB's fast CSV reader
        self.con.execute(f"""
            CREATE OR REPLACE TABLE raw_recipes AS 
            SELECT * FROM read_csv_auto('{csv_path}')
        """)
        
        # Get basic stats
        count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"Loaded {count} recipes into DuckDB")
        
        return count
    
    def clean_ingredient_string(self, ingredient_text):
        """Clean and parse ingredient string using simple regex"""
        if pd.isna(ingredient_text) or not ingredient_text:
            return []
        
        # Convert to string and handle different formats
        ingredient_text = str(ingredient_text).strip('[]"\'')
        
        # Split by common delimiters
        if ',' in ingredient_text:
            raw_ingredients = ingredient_text.split(',')
        elif ';' in ingredient_text:
            raw_ingredients = ingredient_text.split(';')
        else:
            # Try to split by quotes if it looks like a list
            raw_ingredients = re.findall(r'"([^"]*)"', ingredient_text)
            if not raw_ingredients:
                raw_ingredients = [ingredient_text]
        
        clean_ingredients = []
        for ingredient in raw_ingredients:
            cleaned = self.clean_single_ingredient(ingredient)
            if cleaned:
                clean_ingredients.append(cleaned)
        
        return clean_ingredients
    
    def clean_single_ingredient(self, ingredient):
        """Clean a single ingredient string"""
        if not ingredient:
            return None
            
        ingredient = str(ingredient).strip(' "\'')
        
        # Remove quantities and measurements
        ingredient = re.sub(
            r'\b\d+[\s\-]*(?:\d+/\d+)?[\s\-]*(?:cups?|tbsp?|tsp?|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|liters?)\b',
            '', ingredient, flags=re.IGNORECASE
        )
        
        # Remove numbers at the beginning
        ingredient = re.sub(r'^\d+[\s\-]*(?:\d+/\d+)?[\s\-]*', '', ingredient)
        
        # Remove parentheses content
        ingredient = re.sub(r'\([^)]*\)', '', ingredient)
        
        # Remove common preparation words
        prep_words = [
            'chopped', 'diced', 'sliced', 'minced', 'crushed', 'ground',
            'grated', 'shredded', 'melted', 'softened', 'fresh', 'frozen',
            'dried', 'canned', 'optional', 'to taste', 'or more', 'as needed'
        ]
        
        for word in prep_words:
            ingredient = re.sub(r'\b' + word + r'\b', '', ingredient, flags=re.IGNORECASE)
        
        # Clean up whitespace and convert to lowercase
        ingredient = re.sub(r'\s+', ' ', ingredient).strip(' ,-.')
        ingredient = ingredient.lower()
        
        # Skip if too short or just numbers
        if len(ingredient) < 2 or ingredient.isdigit():
            return None
        
        return ingredient
    
    def classify_dietary_simple(self, ingredients_list):
        """Simple keyword-based dietary classification"""
        if not ingredients_list:
            return {
                'is_vegetarian': True,
                'is_vegan': True,
                'is_dessert': False
            }
        
        # Join all ingredients into one text for easier searching
        ingredients_text = ' '.join(ingredients_list).lower()
        
        # Check for meat/fish
        has_meat = any(meat in ingredients_text for meat in self.meat_keywords)
        
        # Check for dairy/eggs
        has_dairy = any(dairy in ingredients_text for dairy in self.dairy_egg_keywords)
        
        # Check for dessert indicators
        dessert_count = sum(1 for dessert in self.dessert_keywords if dessert in ingredients_text)
        is_dessert = dessert_count >= 2  # Need multiple dessert keywords
        
        return {
            'is_vegetarian': not has_meat,
            'is_vegan': not (has_meat or has_dairy),
            'is_dessert': is_dessert
        }
    
    def extract_cooking_time(self, directions):
        """Extract cooking time from directions using regex"""
        if pd.isna(directions):
            return None
        
        directions_lower = str(directions).lower()
        
        # Time patterns
        patterns = [
            # "30 minutes", "45 mins"
            (r'(\d+)\s*(?:minutes?|mins?)\b', 1),
            # "2 hours", "1.5 hrs"
            (r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b', 60),
            # "1 hour 30 minutes"
            (r'(\d+)\s*(?:hours?|hrs?)\s*(?:and\s*)?(\d+)?\s*(?:minutes?|mins?)?', None)
        ]
        
        for pattern, multiplier in patterns:
            matches = re.findall(pattern, directions_lower)
            if matches:
                if multiplier is None:  # Complex pattern
                    total = 0
                    for match in matches:
                        if isinstance(match, tuple):
                            hours = int(match[0]) if match[0] else 0
                            minutes = int(match[1]) if len(match) > 1 and match[1] else 0
                            total = hours * 60 + minutes
                        break
                    return total if total > 0 else None
                else:
                    # Simple pattern
                    time_value = float(matches[0])
                    return min(int(time_value * multiplier), 1440)  # Cap at 24 hours
        
        return None
    
    def process_recipes_batch(self, batch_size=10000):
        """Process recipes in batches using simple text processing"""
        print("Processing recipes with simple text processing...")
        
        # Get total count
        total_count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"Processing {total_count} recipes in batches of {batch_size}")
        
        # Process in batches
        for offset in range(0, total_count, batch_size):
            print(f"Processing batch {offset//batch_size + 1}/{(total_count + batch_size - 1)//batch_size}")
            
            # Get batch data
            batch_df = self.con.execute(f"""
                SELECT * FROM raw_recipes 
                LIMIT {batch_size} OFFSET {offset}
            """).fetchdf()
            
            # Process each recipe in batch
            processed_batch = []
            
            for idx, row in batch_df.iterrows():
                # Extract and clean ingredients
                clean_ingredients = self.clean_ingredient_string(row.get('ingredients', ''))
                
                # Classify dietary restrictions
                dietary_info = self.classify_dietary_simple(clean_ingredients)
                
                # Extract cooking time
                cooking_time = self.extract_cooking_time(row.get('directions', ''))
                
                processed_batch.append({
                    'recipe_id': row.get('recipe_id', idx) or idx,
                    'title': row.get('title', '') or '',
                    'ingredients': row.get('ingredients', '') or '',
                    'directions': row.get('directions', '') or '',
                    'rating': float(row.get('rating', 0)) if pd.notna(row.get('rating')) else None,
                    'cuisine_type': row.get('cuisine_type', '') or '',
                    'ingredients_clean': clean_ingredients,
                    'ingredient_count': len(clean_ingredients),
                    'cooking_time': cooking_time,
                    'is_vegetarian': dietary_info['is_vegetarian'],
                    'is_vegan': dietary_info['is_vegan'],
                    'is_dessert': dietary_info['is_dessert']
                })
            
            # Insert batch into processed table
            processed_df = pd.DataFrame(processed_batch)
            
            # Insert batch directly using parameterized queries to avoid type issues
            for recipe in processed_batch:
                try:
                    self.con.execute("""
                        INSERT OR REPLACE INTO recipes (
                            recipe_id, title, ingredients, directions, rating, 
                            cuisine_type, ingredients_clean, ingredient_count, 
                            cooking_time, is_vegetarian, is_vegan, is_dessert
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        recipe['recipe_id'],
                        recipe['title'],
                        recipe['ingredients'], 
                        recipe['directions'],
                        recipe['rating'],
                        recipe['cuisine_type'],
                        recipe['ingredients_clean'],
                        recipe['ingredient_count'],
                        recipe['cooking_time'],
                        recipe['is_vegetarian'],
                        recipe['is_vegan'],
                        recipe['is_dessert']
                    ])
                except Exception as e:
                    print(f"Error inserting recipe {recipe['recipe_id']}: {e}")
                    continue
        
        print("Processing complete!")
    
    def get_statistics(self):
        """Get comprehensive statistics using DuckDB"""
        stats = self.con.execute("""
            SELECT 
                COUNT(*) as total_recipes,
                SUM(CASE WHEN is_vegetarian THEN 1 ELSE 0 END) as vegetarian_count,
                SUM(CASE WHEN is_vegan THEN 1 ELSE 0 END) as vegan_count,
                SUM(CASE WHEN is_dessert THEN 1 ELSE 0 END) as dessert_count,
                AVG(ingredient_count) as avg_ingredient_count,
                AVG(cooking_time) as avg_cooking_time,
                COUNT(CASE WHEN cooking_time IS NOT NULL THEN 1 END) as recipes_with_time
            FROM recipes
        """).fetchone()
        
        return {
            'total_recipes': stats[0],
            'vegetarian_count': stats[1],
            'vegan_count': stats[2], 
            'dessert_count': stats[3],
            'avg_ingredient_count': stats[4],
            'avg_cooking_time': stats[5],
            'recipes_with_time': stats[6]
        }
    
    def validate_classifications(self, sample_size=20):
        """Validate dietary classifications by sampling"""
        print("\n=== Validating Classifications ===")
        
        # Get samples of each category
        vegetarian_sample = self.con.execute(f"""
            SELECT title, ingredients_clean
            FROM recipes 
            WHERE is_vegetarian = true
            ORDER BY RANDOM()
            LIMIT {sample_size}
        """).fetchdf()
        
        print(f"Sample vegetarian recipes:")
        for idx, row in vegetarian_sample.head(5).iterrows():
            print(f"- {row['title']}")
            print(f"  Ingredients: {', '.join(row['ingredients_clean'][:5])}...")
        
        # Check for potential misclassifications
        non_veg_in_veg = self.con.execute("""
            SELECT title, ingredients_clean
            FROM recipes 
            WHERE is_vegetarian = true
            AND (
                list_contains(ingredients_clean, 'chicken') OR
                list_contains(ingredients_clean, 'beef') OR
                list_contains(ingredients_clean, 'fish')
            )
            LIMIT 5
        """).fetchdf()
        
        if not non_veg_in_veg.empty:
            print(f"\nPotential misclassifications found:")
            for idx, row in non_veg_in_veg.iterrows():
                print(f"- {row['title']}: {row['ingredients_clean']}")
        
        return vegetarian_sample

# Usage example
if __name__ == "__main__":
    # Initialize processor
    processor = SimpleRecipeProcessor()
    
    # Load your data
    csv_path = "full_dataset.csv"  # Update with your path
    processor.load_data_from_csv(csv_path)
    
    # Process with simple text processing
    processor.process_recipes_batch(batch_size=5000)
    
    # Get statistics
    stats = processor.get_statistics()
    print("\n=== Processing Statistics ===")
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2f}")
        else:
            print(f"{key}: {value}")
    
    # Validate classifications
    processor.validate_classifications()
    
    print("\n=== Simple Recipe Processor Ready! ===")
    print("Your recipes are now processed with:")
    print("- Simple ingredient cleaning")
    print("- Keyword-based dietary classification")
    print("- Fast DuckDB storage")
    print("- No ML dependencies!")