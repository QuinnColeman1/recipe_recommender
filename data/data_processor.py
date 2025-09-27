import duckdb
import pandas as pd
import re
import numpy as np
from pathlib import Path
import warnings
import time
import argparse
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import gc  # For garbage collection
warnings.filterwarnings('ignore')

# Compile regex patterns once
QUANTITY_PATTERN = re.compile(
    r'\b\d+[\s\-]*(?:\d+/\d+)?[\s\-]*(?:cups?|tbsp?|tsp?|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|liters?)\b',
    flags=re.IGNORECASE
)
PREP_WORDS = re.compile(
    r'\b(?:chopped|diced|sliced|minced|crushed|ground|grated|shredded|melted|softened|fresh|frozen|dried|canned|optional|to taste|or more|as needed)\b',
    flags=re.IGNORECASE
)
PARENTHESES = re.compile(r'\([^)]*\)')
NUMBER_PREFIX = re.compile(r'^\d+[\s\-]*(?:\d+/\d+)?[\s\-]*')
WHITESPACE = re.compile(r'\s+')

# Standalone functions for multiprocessing
def clean_single_ingredient_standalone(ingredient):
    """Standalone version of clean_single_ingredient for multiprocessing"""
    if not ingredient:
        return None
        
    # Convert to string and clean
    ingredient = str(ingredient).strip(' \"\'')
    if len(ingredient) < 2:
        return None
        
    # Remove quantities and measurements
    ingredient = QUANTITY_PATTERN.sub('', ingredient)
    
    # Remove numbers at the beginning
    ingredient = NUMBER_PREFIX.sub('', ingredient)
    
    # Remove parentheses content
    ingredient = PARENTHESES.sub('', ingredient)
    
    # Remove common preparation words
    ingredient = PREP_WORDS.sub('', ingredient)
    
    # Clean up whitespace and convert to lowercase
    ingredient = WHITESPACE.sub(' ', ingredient).strip(' ,-.').lower()
    
    # Skip if too short or just numbers
    if len(ingredient) < 2 or ingredient.isdigit():
        return None
        
    return ingredient

def process_ingredient_batch_standalone(ingredients_list):
    """Standalone version for multiprocessing"""
    return [ing for ing in map(clean_single_ingredient_standalone, ingredients_list) if ing]

class SimpleRecipeProcessor:
    def __init__(self, db_path='recipes.db'):
        """Initialize with DuckDB only - no ML dependencies"""
        # Use a more conservative memory configuration for DuckDB
        self.con = duckdb.connect(db_path, config={
            'memory_limit': '1GB',  # Limit DuckDB memory usage
            'threads': 4  # Limit thread usage
        })
        
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
    
    def load_data_from_csv(self, csv_path, limit=None):
        """Load CSV data into DuckDB efficiently without loading all into memory"""
        print(f"Loading data from {csv_path}...")
        
        # First, get column names from a small sample
        sample_df = pd.read_csv(csv_path, nrows=5)
        sample_df.columns = sample_df.columns.str.strip().str.lower()
        
        # Ensure required columns exist
        required_columns = {'title', 'ingredients', 'directions'}
        missing_columns = required_columns - set(sample_df.columns)
        if missing_columns:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing_columns)}")
        
        print(f"Available columns: {', '.join(sample_df.columns)}")
        
        try:
            # Method 1: Use DuckDB's efficient CSV reader
            # This reads the CSV directly without loading it all into memory
            limit_clause = f"LIMIT {limit}" if limit else ""
            
            # Create the raw_recipes table directly from CSV
            self.con.execute(f"""
                CREATE OR REPLACE TABLE raw_recipes AS 
                SELECT * FROM read_csv_auto(
                    '{csv_path}',
                    header=true,
                    sample_size=10000,
                    all_varchar=false,
                    normalize_names=true
                ) {limit_clause}
            """)
            
        except Exception as e:
            print(f"DuckDB direct CSV reading failed: {e}")
            print("Falling back to chunked pandas reading...")
            
            # Method 2: Fallback to chunked pandas reading
            chunk_size = 50000
            chunks_processed = 0
            
            # Create table from first chunk to get schema
            first_chunk = True
            
            for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
                # Normalize column names
                chunk.columns = chunk.columns.str.strip().str.lower()
                
                if first_chunk:
                    # Create table with first chunk
                    self.con.register('temp_chunk', chunk)
                    self.con.execute("""
                        CREATE OR REPLACE TABLE raw_recipes AS 
                        SELECT * FROM temp_chunk
                    """)
                    first_chunk = False
                else:
                    # Append subsequent chunks
                    self.con.register('temp_chunk', chunk)
                    self.con.execute("""
                        INSERT INTO raw_recipes
                        SELECT * FROM temp_chunk
                    """)
                
                chunks_processed += len(chunk)
                print(f"Loaded {chunks_processed:,} recipes...", end='\r')
                
                # Stop if we've reached the limit
                if limit and chunks_processed >= limit:
                    # Trim to exact limit if we went over
                    if chunks_processed > limit:
                        self.con.execute(f"""
                            DELETE FROM raw_recipes 
                            WHERE rowid > {limit}
                        """)
                    break
        
        # Get the count of loaded records
        count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"\nLoaded {count:,} recipes into DuckDB")
        
        # Normalize column names to lowercase
        columns = self.con.execute("SELECT * FROM raw_recipes LIMIT 1").description
        for col in columns:
            col_name = col[0]
            if col_name != col_name.lower():
                try:
                    self.con.execute(f'ALTER TABLE raw_recipes RENAME COLUMN "{col_name}" TO {col_name.lower()}')
                except:
                    pass  # Column might already be lowercase
        
        return count
    
    def clean_ingredient_string_batch(self, ingredients_series, use_multiprocessing=False):
        """Clean and parse ingredient strings in batch"""
        if ingredients_series.empty:
            return pd.Series([[]] * len(ingredients_series))
        
        # Convert to string and clean
        ingredients = ingredients_series.astype(str).str.strip('[]\"\'')
        
        # Split by common delimiters
        split_ingredients = []
        for text in ingredients:
            if ',' in text:
                parts = [p.strip() for p in text.split(',') if p.strip()]
            elif ';' in text:
                parts = [p.strip() for p in text.split(';') if p.strip()]
            else:
                parts = re.findall(r'"([^"]*)"', text) or [text]
            split_ingredients.append(parts)
        
        # Process ingredients
        if use_multiprocessing and len(split_ingredients) > 100:
            # Only use multiprocessing for larger batches
            try:
                with ProcessPoolExecutor(max_workers=min(4, multiprocessing.cpu_count())) as executor:
                    cleaned_ingredients = list(tqdm(
                        executor.map(process_ingredient_batch_standalone, split_ingredients),
                        total=len(split_ingredients),
                        desc="Cleaning ingredients (parallel)"
                    ))
            except Exception as e:
                print(f"Multiprocessing failed: {e}, falling back to serial processing")
                cleaned_ingredients = [
                    process_ingredient_batch_standalone(ingredients_list) 
                    for ingredients_list in tqdm(split_ingredients, desc="Cleaning ingredients (serial)")
                ]
        else:
            # For smaller batches, process serially (faster due to overhead)
            cleaned_ingredients = [
                process_ingredient_batch_standalone(ingredients_list) 
                for ingredients_list in tqdm(split_ingredients, desc="Cleaning ingredients")
            ]
        
        return pd.Series(cleaned_ingredients)
    
    def clean_single_ingredient(self, ingredient):
        """Clean a single ingredient string"""
        return clean_single_ingredient_standalone(ingredient)
    
    def classify_dietary_simple(self, ingredients_list):
        """Optimized keyword-based dietary classification"""
        if not ingredients_list:
            return {
                'is_vegetarian': True,
                'is_vegan': True,
                'is_dessert': False
            }
        
        # Join all ingredients into one text for easier searching
        ingredients_text = ' '.join(ingredients_list).lower()
        
        # Use set for faster lookups
        ingredients_set = set(ingredients_list)
        
        # Check for meat/fish using set intersection for exact matches
        has_meat = any(meat in ingredients_set for meat in self.meat_keywords)
        
        # If no exact matches, fall back to substring search
        if not has_meat:
            has_meat = any(meat in ingredients_text for meat in self.meat_keywords)
        
        # Check for dairy/eggs
        has_dairy = any(dairy in ingredients_text for dairy in self.dairy_egg_keywords)
        
        # Check for dessert indicators with early exit
        dessert_count = 0
        for dessert in self.dessert_keywords:
            if dessert in ingredients_text:
                dessert_count += 1
                if dessert_count >= 2:  # Early exit if we find enough dessert indicators
                    is_dessert = True
                    break
        else:
            is_dessert = dessert_count >= 2
        
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
    
    def process_recipes_batch(self, batch_size=50000, limit=None):
        """Process recipes in batches using optimized text processing"""
        print("Starting recipe processing...")
        start_time = time.time()
        
        # Get total count
        total_count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"Processing {total_count:,} recipes in batches of {batch_size:,}")
        
        # Since we may have already limited at load time, use the actual count
        # The limit was already applied during load_data_from_csv
        
        # Calculate total batches
        total_batches = (total_count + batch_size - 1) // batch_size
        
        # Process in batches
        for batch_num in tqdm(range(total_batches), desc="Processing batches"):
            offset = batch_num * batch_size
            batch_start = time.time()
            
            # Get batch data with explicit column selection
            batch_df = self.con.execute(f"""
                SELECT 
                    *,
                    ROW_NUMBER() OVER () as row_id
                FROM raw_recipes 
                ORDER BY row_id
                LIMIT {batch_size} OFFSET {offset}
            """).fetchdf()
            
            if batch_df.empty:
                continue
                
            # Ensure we have the required columns
            if 'ingredients' not in batch_df.columns:
                raise ValueError("'ingredients' column not found in the batch data. Available columns: " + 
                               ", ".join(batch_df.columns))
            
            # Process ingredients in batch (use multiprocessing only for larger batches)
            # Disable multiprocessing for small batches to avoid overhead
            use_mp = len(batch_df) > 1000 and batch_size > 1000
            batch_df['ingredients_clean'] = self.clean_ingredient_string_batch(
                batch_df['ingredients'], 
                use_multiprocessing=use_mp
            )
            batch_df['ingredient_count'] = batch_df['ingredients_clean'].apply(len)
            
            # Classify dietary restrictions
            dietary_info = batch_df['ingredients_clean'].apply(self.classify_dietary_simple)
            batch_df = pd.concat([
                batch_df,
                pd.json_normalize(dietary_info)
            ], axis=1)
            
            # Extract cooking times
            if 'directions' in batch_df.columns:
                batch_df['cooking_time'] = batch_df['directions'].apply(self.extract_cooking_time)
            
            # Prepare data for insertion - use row_id if 'id' column doesn't exist
            if 'id' in batch_df.columns:
                batch_df = batch_df.rename(columns={'id': 'recipe_id'})
            elif 'row_id' in batch_df.columns:
                batch_df = batch_df.rename(columns={'row_id': 'recipe_id'})
            else:
                batch_df['recipe_id'] = range(offset + 1, offset + 1 + len(batch_df))
            
            # Handle missing values
            batch_df['rating'] = pd.to_numeric(batch_df.get('rating'), errors='coerce')
            batch_df['cuisine_type'] = batch_df.get('cuisine_type', '')
            
            # Insert batch using DuckDB's fast path
            try:
                # Create a temporary table for the batch
                cols_to_insert = ['recipe_id', 'title', 'ingredients', 'directions', 
                                 'ingredients_clean', 'ingredient_count',
                                 'cooking_time', 'is_vegetarian', 'is_vegan', 'is_dessert']
                
                # Add optional columns if they exist
                if 'rating' in batch_df.columns:
                    cols_to_insert.insert(4, 'rating')
                if 'cuisine_type' in batch_df.columns:
                    cols_to_insert.insert(5, 'cuisine_type')
                
                # Filter to only include columns that exist
                cols_to_insert = [col for col in cols_to_insert if col in batch_df.columns]
                
                self.con.register('temp_batch', batch_df[cols_to_insert])
                
                # Build column list for insert
                insert_cols = ', '.join(cols_to_insert)
                placeholders = ', '.join(['?' for _ in cols_to_insert])
                
                # Use INSERT OR REPLACE to handle duplicates
                self.con.execute(f"""
                    INSERT OR REPLACE INTO recipes ({insert_cols})
                    SELECT {insert_cols} FROM temp_batch
                """)
                
                # Commit after each batch
                self.con.commit()
                
                batch_time = time.time() - batch_start
                items_per_sec = len(batch_df) / batch_time if batch_time > 0 else 0
                
                print(f"\nProcessed batch {batch_num + 1}/{total_batches} "
                      f"({len(batch_df):,} items, {items_per_sec:.1f} items/sec)")
                
            except Exception as e:
                print(f"\nError processing batch {batch_num + 1}: {str(e)}")
                # If batch fails, try processing individual records
                self._process_failed_batch(batch_df)
            
            # Always clean up memory after each batch
            del batch_df
            gc.collect()
        
        total_time = time.time() - start_time
        print(f"\nProcessing complete! Total time: {total_time/60:.1f} minutes")
        print(f"Average speed: {total_count/total_time:.1f} items/second")
    
    def _process_failed_batch(self, batch_df):
        """Process individual records if batch insert fails"""
        success = 0
        for _, row in tqdm(batch_df.iterrows(), total=len(batch_df), desc="Processing failed batch"):
            try:
                self.con.execute("""
                    INSERT OR REPLACE INTO recipes (
                        recipe_id, title, ingredients, directions, rating, 
                        cuisine_type, ingredients_clean, ingredient_count, 
                        cooking_time, is_vegetarian, is_vegan, is_dessert
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    row.get('recipe_id'),
                    row.get('title', ''),
                    row.get('ingredients', ''),
                    row.get('directions', ''),
                    row.get('rating'),
                    row.get('cuisine_type', ''),
                    row.get('ingredients_clean', []),
                    row.get('ingredient_count', 0),
                    row.get('cooking_time'),
                    row.get('is_vegetarian', False),
                    row.get('is_vegan', False),
                    row.get('is_dessert', False)
                ])
                success += 1
            except Exception as e:
                print(f"Error inserting recipe {row.get('recipe_id')}: {e}")
        
        if success < len(batch_df):
            print(f"Warning: Only {success} of {len(batch_df)} records were processed in the failed batch")
    
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
            'total_recipes': stats[0] or 0,
            'vegetarian_count': stats[1] or 0,
            'vegan_count': stats[2] or 0, 
            'dessert_count': stats[3] or 0,
            'avg_ingredient_count': stats[4] or 0,
            'avg_cooking_time': stats[5] or 0,
            'recipes_with_time': stats[6] or 0
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
def parse_arguments():
    parser = argparse.ArgumentParser(description='Process recipe data with configurable batch size and limit.')
    parser.add_argument('--batch-size', type=int, default=10000,
                       help='Number of recipes to process in each batch (default: 10000)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Maximum number of recipes to process in total (default: None, process all)')
    parser.add_argument('--csv-path', type=str, default=None,
                       help='Path to the CSV file (default: full_dataset.csv in the same directory)')
    parser.add_argument('--db-path', type=str, default=None,
                       help='Path to the output database (default: data/recipes.db)')
    parser.add_argument('--validate', type=int, default=10,
                       help='Number of samples to validate (default: 10, set to 0 to skip validation)')
    return parser.parse_args()

def main():
    try:
        args = parse_arguments()
        
        # Set up database path
        if args.db_path is None:
            import os
            db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, 'recipes.db')
        else:
            db_path = args.db_path
        
        # Initialize processor
        print(f"Initializing processor with database: {db_path}")
        processor = SimpleRecipeProcessor(db_path=db_path)
        
        # Set up CSV path
        if args.csv_path is None:
            import os
            csv_path = os.path.join(os.path.dirname(__file__), "full_dataset.csv")
        else:
            csv_path = args.csv_path
            
        print(f"Loading data from {csv_path}...")
        # Pass the limit to load_data_from_csv to avoid loading unnecessary data
        processor.load_data_from_csv(csv_path, limit=args.limit)
        
        # Process with optimized text processing
        print("\nStarting batch processing...")
        start_time = time.time()
        
        # Process with specified batch size and limit
        print(f"Processing {'all recipes' if args.limit is None else f'up to {args.limit:,} recipes'} "
              f"in batches of {args.batch_size:,}")
              
        processor.process_recipes_batch(batch_size=args.batch_size, limit=args.limit)
        
        # Get and display statistics
        print("\nGenerating statistics...")
        stats = processor.get_statistics()
        
        print("\n=== Processing Statistics ===")
        for key, value in stats.items():
            if isinstance(value, float):
                print(f"{key}: {value:,.2f}")
            else:
                print(f"{key}: {value:,}")
        
        # Validate a small sample if requested
        if args.validate > 0:
            print(f"\nValidating classifications ({args.validate} samples)...")
            processor.validate_classifications(sample_size=args.validate)
        
        total_time = (time.time() - start_time) / 60
        print(f"\n=== Processing Complete! ===")
        print(f"Total processing time: {total_time:.1f} minutes")
        print(f"Average speed: {stats['total_recipes']/(total_time*60):.1f} recipes/second")
        
    except Exception as e:
        print(f"\nError during processing: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()