import duckdb
import pandas as pd
import re
import warnings
import time
import argparse
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import gc  # For garbage collection

warnings.filterwarnings("ignore")

# Compile regex patterns once
QUANTITY_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(cups?|tbsp?|tsp?|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|liters?|quarts?|pints?|gallons?)\b",
    flags=re.IGNORECASE,
)
PREP_WORDS = re.compile(
    r"\b(?:chopped|diced|sliced|minced|crushed|ground|grated|shredded|melted|softened|fresh|frozen|dried|canned|optional|to taste|or more|as needed)\b",
    flags=re.IGNORECASE,
)
PARENTHESES = re.compile(r"\([^)]*\)")
NUMBER_PREFIX = re.compile(r"^\d+[\s\-]*(?:\d+/\d+)?[\s\-]*")
WHITESPACE = re.compile(r"\s+")

# Additional patterns for metadata extraction
SERVINGS_PATTERN = re.compile(
    r"(?:makes?|serves?|yield[s]?|portions?|servings?)[:\s]+(\d+(?:-\d+)?)",
    flags=re.IGNORECASE,
)
PREP_TIME_PATTERN = re.compile(
    r"prep(?:aration)?[\s:]+(\d+)\s*(?:minutes?|mins?|hours?|hrs?)", flags=re.IGNORECASE
)
COOK_TIME_PATTERN = re.compile(
    r"(?:cook|bake|simmer|roast)(?:ing)?[\s:]+(\d+)\s*(?:minutes?|mins?|hours?|hrs?)",
    flags=re.IGNORECASE,
)


# Standalone functions for multiprocessing
def clean_single_ingredient_standalone(ingredient):
    """Standalone version of clean_single_ingredient for multiprocessing"""
    if not ingredient:
        return None, None, None  # cleaned, original, quantity

    # Store original
    original = str(ingredient).strip(" \"'")

    # Convert to string and clean
    ingredient = original
    if len(ingredient) < 2:
        return None, None, None

    # Extract quantity before removing it
    quantity_match = QUANTITY_PATTERN.search(ingredient)
    quantity = quantity_match.group(0) if quantity_match else None

    # Remove quantities and measurements
    ingredient = QUANTITY_PATTERN.sub("", ingredient)

    # Remove numbers at the beginning
    ingredient = NUMBER_PREFIX.sub("", ingredient)

    # Remove parentheses content
    ingredient = PARENTHESES.sub("", ingredient)

    # Remove common preparation words
    ingredient = PREP_WORDS.sub("", ingredient)

    # Clean up whitespace and convert to lowercase
    ingredient = WHITESPACE.sub(" ", ingredient).strip(" ,-.").lower()

    # Skip if too short or just numbers
    if len(ingredient) < 2 or ingredient.isdigit():
        return None, None, None

    # Normalize plurals (simple approach)
    if ingredient.endswith("ies"):
        ingredient = ingredient[:-3] + "y"
    elif ingredient.endswith("es"):
        ingredient = ingredient[:-2]
    elif ingredient.endswith("s") and not ingredient.endswith("ss"):
        ingredient = ingredient[:-1]

    return ingredient, original, quantity


def process_ingredient_batch_standalone(ingredients_list):
    """Standalone version for multiprocessing - returns cleaned, originals, and quantities"""
    cleaned = []
    originals = []
    quantities = []

    for ing in ingredients_list:
        clean, orig, quant = clean_single_ingredient_standalone(ing)
        if clean:
            cleaned.append(clean)
            originals.append(orig)
            quantities.append(quant)

    return cleaned, originals, quantities


# Ingredient categorization function
def categorize_ingredient(ingredient):
    """Categorize an ingredient into food groups"""
    ingredient_lower = ingredient.lower() if ingredient else ""

    categories = {
        "protein": [
            "chicken",
            "beef",
            "pork",
            "lamb",
            "turkey",
            "duck",
            "fish",
            "salmon",
            "tuna",
            "shrimp",
            "crab",
            "lobster",
            "egg",
            "tofu",
            "tempeh",
            "seitan",
            "bean",
            "lentil",
            "chickpea",
        ],
        "dairy": [
            "milk",
            "cream",
            "cheese",
            "butter",
            "yogurt",
            "cheddar",
            "mozzarella",
            "parmesan",
            "cottage cheese",
            "sour cream",
        ],
        "grain": [
            "rice",
            "pasta",
            "bread",
            "flour",
            "wheat",
            "oat",
            "quinoa",
            "barley",
            "couscous",
            "bulgur",
            "noodle",
            "cereal",
        ],
        "vegetable": [
            "tomato",
            "onion",
            "garlic",
            "carrot",
            "celery",
            "potato",
            "broccoli",
            "cauliflower",
            "spinach",
            "lettuce",
            "pepper",
            "zucchini",
            "cucumber",
            "mushroom",
            "cabbage",
            "kale",
        ],
        "fruit": [
            "apple",
            "banana",
            "orange",
            "lemon",
            "lime",
            "grape",
            "berry",
            "strawberry",
            "blueberry",
            "peach",
            "pear",
            "cherry",
            "mango",
        ],
        "nuts_seeds": [
            "almond",
            "walnut",
            "pecan",
            "cashew",
            "peanut",
            "hazelnut",
            "pistachio",
            "sunflower",
            "pumpkin seed",
            "chia",
            "flax",
        ],
        "herbs_spices": [
            "salt",
            "pepper",
            "basil",
            "oregano",
            "thyme",
            "rosemary",
            "parsley",
            "cilantro",
            "cumin",
            "paprika",
            "cinnamon",
        ],
        "oils_fats": [
            "oil",
            "olive oil",
            "vegetable oil",
            "coconut oil",
            "butter",
            "margarine",
            "shortening",
            "lard",
        ],
        "sweetener": ["sugar", "honey", "maple", "syrup", "stevia", "agave"],
        "condiment": ["ketchup", "mustard", "mayo", "vinegar", "sauce", "dressing"],
    }

    for category, keywords in categories.items():
        if any(keyword in ingredient_lower for keyword in keywords):
            return category

    return "other"


class EnhancedRecipeProcessor:
    def __init__(self, db_path="recipes.db"):
        """Initialize with DuckDB only - no ML dependencies"""
        # Use a more conservative memory configuration for DuckDB
        self.con = duckdb.connect(
            db_path,
            config={
                "memory_limit": "1GB",  # Limit DuckDB memory usage
                "threads": 4,  # Limit thread usage
            },
        )

        # Define ingredient blacklists for dietary classification
        self.meat_keywords = [
            "chicken",
            "beef",
            "pork",
            "lamb",
            "turkey",
            "duck",
            "meat",
            "poultry",
            "bacon",
            "ham",
            "sausage",
            "pepperoni",
            "salami",
            "prosciutto",
            "fish",
            "salmon",
            "tuna",
            "shrimp",
            "crab",
            "lobster",
            "seafood",
            "steak",
            "ribs",
            "wings",
            "ground beef",
            "hamburger",
            "veal",
            "venison",
        ]

        self.dairy_egg_keywords = [
            "milk",
            "cream",
            "cheese",
            "butter",
            "yogurt",
            "eggs",
            "egg",
            "cheddar",
            "mozzarella",
            "parmesan",
            "mayo",
            "mayonnaise",
            "ice cream",
            "cottage cheese",
            "sour cream",
            "whey",
            "casein",
        ]

        # Additional dietary keywords
        self.gluten_keywords = [
            "flour",
            "wheat",
            "bread",
            "pasta",
            "noodle",
            "barley",
            "rye",
            "breadcrumb",
            "cracker",
            "cereal",
            "couscous",
            "bulgur",
            "seitan",
            "beer",
            "soy sauce",
            "teriyaki",
        ]

        self.nut_keywords = [
            "almond",
            "walnut",
            "pecan",
            "cashew",
            "peanut",
            "hazelnut",
            "pistachio",
            "macadamia",
            "brazil nut",
            "pine nut",
            "chestnut",
            "nut butter",
            "nutella",
        ]

        # High carb ingredients for low-carb/keto detection
        self.high_carb_keywords = [
            "sugar",
            "flour",
            "bread",
            "pasta",
            "rice",
            "potato",
            "corn",
            "bean",
            "lentil",
            "oat",
            "quinoa",
            "honey",
            "maple",
            "agave",
            "banana",
            "grape",
            "raisin",
            "date",
        ]

        # Nutritional indicators
        self.high_protein_keywords = [
            "chicken",
            "beef",
            "pork",
            "fish",
            "egg",
            "tofu",
            "bean",
            "lentil",
            "quinoa",
            "protein powder",
            "greek yogurt",
            "cottage cheese",
        ]

        self.low_fat_keywords = [
            "lean",
            "skinless",
            "low-fat",
            "nonfat",
            "skim",
            "light",
        ]

        self.high_fiber_keywords = [
            "whole wheat",
            "whole grain",
            "bran",
            "oat",
            "bean",
            "lentil",
            "broccoli",
            "artichoke",
            "avocado",
            "chia",
            "flax",
            "quinoa",
        ]

        self.dessert_keywords = [
            "cake",
            "cookie",
            "brownie",
            "pie",
            "chocolate",
            "sugar",
            "dessert",
            "sweet",
            "frosting",
            "icing",
            "candy",
            "syrup",
            "cupcake",
            "tart",
            "pudding",
            "ice cream",
        ]

        # Meal type keywords
        self.breakfast_keywords = [
            "breakfast",
            "pancake",
            "waffle",
            "cereal",
            "oatmeal",
            "toast",
            "egg",
            "bacon",
            "sausage",
            "muffin",
            "bagel",
            "smoothie",
        ]

        self.lunch_keywords = ["lunch", "sandwich", "salad", "soup", "wrap", "burger"]

        self.dinner_keywords = [
            "dinner",
            "roast",
            "steak",
            "pasta",
            "casserole",
            "curry",
        ]

        # Initialize database
        self.setup_database()

    def setup_database(self):
        """Setup DuckDB with enhanced schema"""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                recipe_id INTEGER PRIMARY KEY,
                title VARCHAR,
                ingredients TEXT,
                directions TEXT,
                rating FLOAT,
                
                -- Time fields
                prep_time INTEGER,
                cook_time INTEGER,
                total_time INTEGER,
                
                -- Recipe metadata
                servings INTEGER,
                difficulty_level VARCHAR,
                meal_type VARCHAR,
                cuisine_type VARCHAR,
                
                -- Processed ingredient fields
                ingredients_clean TEXT[],
                ingredients_original TEXT[],
                ingredient_quantities TEXT[],
                ingredient_categories TEXT[],
                ingredient_count INTEGER,
                
                -- Dietary classifications
                is_vegetarian BOOLEAN,
                is_vegan BOOLEAN,
                is_gluten_free BOOLEAN,
                is_dairy_free BOOLEAN,
                is_nut_free BOOLEAN,
                is_low_carb BOOLEAN,
                is_dessert BOOLEAN,
                
                -- Nutritional indicators
                is_high_protein BOOLEAN,
                is_low_fat BOOLEAN,
                is_high_fiber BOOLEAN,
                
                -- Data quality fields
                has_complete_directions BOOLEAN,
                ingredient_quality_score FLOAT,
                recipe_completeness_score FLOAT,
                
                -- Search optimization
                search_text TEXT
            )
        """)

    def load_data_from_csv(self, csv_path, limit=None):
        """Load CSV data into DuckDB efficiently without loading all into memory"""
        print(f"Loading data from {csv_path}...")

        # First, get column names from a small sample
        sample_df = pd.read_csv(csv_path, nrows=5)
        sample_df.columns = sample_df.columns.str.strip().str.lower()

        # Ensure required columns exist
        required_columns = {"title", "ingredients", "directions"}
        missing_columns = required_columns - set(sample_df.columns)
        if missing_columns:
            raise ValueError(
                f"CSV is missing required columns: {', '.join(missing_columns)}"
            )

        print(f"Available columns: {', '.join(sample_df.columns)}")

        try:
            # Method 1: Use DuckDB's efficient CSV reader
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
            first_chunk = True

            for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
                chunk.columns = chunk.columns.str.strip().str.lower()

                if first_chunk:
                    self.con.register("temp_chunk", chunk)
                    self.con.execute("""
                        CREATE OR REPLACE TABLE raw_recipes AS 
                        SELECT * FROM temp_chunk
                    """)
                    first_chunk = False
                else:
                    self.con.register("temp_chunk", chunk)
                    self.con.execute("""
                        INSERT INTO raw_recipes
                        SELECT * FROM temp_chunk
                    """)

                chunks_processed += len(chunk)
                print(f"Loaded {chunks_processed:,} recipes...", end="\r")

                if limit and chunks_processed >= limit:
                    if chunks_processed > limit:
                        self.con.execute(f"""
                            DELETE FROM raw_recipes 
                            WHERE rowid > {limit}
                        """)
                    break

        count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"\nLoaded {count:,} recipes into DuckDB")

        # Normalize column names to lowercase
        columns = self.con.execute("SELECT * FROM raw_recipes LIMIT 1").description
        for col in columns:
            col_name = col[0]
            if col_name != col_name.lower():
                try:
                    self.con.execute(
                        f'ALTER TABLE raw_recipes RENAME COLUMN "{col_name}" TO {col_name.lower()}'
                    )
                except Exception as e:
                    print(f"Warning: Could not rename column {col_name}: {e}")

        return count

    def clean_ingredient_string_batch(
        self, ingredients_series, use_multiprocessing=False
    ):
        """Clean and parse ingredient strings in batch, returning cleaned, originals, and quantities"""
        if ingredients_series.empty:
            empty = pd.Series([[]] * len(ingredients_series))
            return empty, empty, empty, empty

        # Convert to string and clean
        ingredients = ingredients_series.astype(str).str.strip("[]\"'")

        # Split by common delimiters
        split_ingredients = []
        for text in ingredients:
            if "," in text:
                parts = [p.strip() for p in text.split(",") if p.strip()]
            elif ";" in text:
                parts = [p.strip() for p in text.split(";") if p.strip()]
            else:
                parts = re.findall(r'"([^"]*)"', text) or [text]
            split_ingredients.append(parts)

        # Process ingredients
        if use_multiprocessing and len(split_ingredients) > 100:
            try:
                with ProcessPoolExecutor(
                    max_workers=min(4, multiprocessing.cpu_count())
                ) as executor:
                    results = list(
                        tqdm(
                            executor.map(
                                process_ingredient_batch_standalone, split_ingredients
                            ),
                            total=len(split_ingredients),
                            desc="Cleaning ingredients (parallel)",
                        )
                    )
            except Exception as e:
                print(f"Multiprocessing failed: {e}, falling back to serial processing")
                results = [
                    process_ingredient_batch_standalone(ingredients_list)
                    for ingredients_list in tqdm(
                        split_ingredients, desc="Cleaning ingredients (serial)"
                    )
                ]
        else:
            results = [
                process_ingredient_batch_standalone(ingredients_list)
                for ingredients_list in tqdm(
                    split_ingredients, desc="Cleaning ingredients"
                )
            ]

        # Unpack results
        cleaned_list = [r[0] for r in results]
        originals_list = [r[1] for r in results]
        quantities_list = [r[2] for r in results]

        # Categorize ingredients
        categories_list = []
        for cleaned_ingredients in cleaned_list:
            categories = [categorize_ingredient(ing) for ing in cleaned_ingredients]
            categories_list.append(categories)

        return (
            pd.Series(cleaned_list),
            pd.Series(originals_list),
            pd.Series(quantities_list),
            pd.Series(categories_list),
        )

    def classify_dietary_comprehensive(self, ingredients_list):
        """Comprehensive dietary classification"""
        if not ingredients_list:
            return {
                "is_vegetarian": True,
                "is_vegan": True,
                "is_gluten_free": True,
                "is_dairy_free": True,
                "is_nut_free": True,
                "is_low_carb": True,
                "is_dessert": False,
            }

        # Join all ingredients into one text for easier searching
        ingredients_text = " ".join(ingredients_list).lower()
        ingredients_set = set(ingredients_list)

        # Check for meat/fish
        has_meat = any(meat in ingredients_set for meat in self.meat_keywords)
        if not has_meat:
            has_meat = any(meat in ingredients_text for meat in self.meat_keywords)

        # Check for dairy/eggs
        has_dairy_egg = any(
            item in ingredients_text for item in self.dairy_egg_keywords
        )

        # Check for gluten
        has_gluten = any(gluten in ingredients_text for gluten in self.gluten_keywords)

        # Check for nuts
        has_nuts = any(nut in ingredients_text for nut in self.nut_keywords)

        # Check for high carbs (more than 3 high-carb ingredients = not low carb)
        high_carb_count = sum(
            1 for carb in self.high_carb_keywords if carb in ingredients_text
        )
        is_low_carb = high_carb_count <= 3

        # Check for dessert
        dessert_count = sum(
            1 for dessert in self.dessert_keywords if dessert in ingredients_text
        )
        is_dessert = dessert_count >= 2

        return {
            "is_vegetarian": not has_meat,
            "is_vegan": not (has_meat or has_dairy_egg),
            "is_gluten_free": not has_gluten,
            "is_dairy_free": not has_dairy_egg,
            "is_nut_free": not has_nuts,
            "is_low_carb": is_low_carb and not is_dessert,
            "is_dessert": is_dessert,
        }

    def classify_nutritional(self, ingredients_list, directions=""):
        """Classify nutritional characteristics"""
        if not ingredients_list:
            return {
                "is_high_protein": False,
                "is_low_fat": False,
                "is_high_fiber": False,
            }

        combined_text = " ".join(ingredients_list).lower() + " " + directions.lower()

        # Check for high protein (at least 2 protein sources)
        protein_count = sum(
            1 for protein in self.high_protein_keywords if protein in combined_text
        )
        is_high_protein = protein_count >= 2

        # Check for low fat
        has_low_fat_indicators = any(
            low_fat in combined_text for low_fat in self.low_fat_keywords
        )
        has_high_fat = any(
            fat in combined_text for fat in ["fried", "deep fry", "cream", "butter"]
        )
        is_low_fat = has_low_fat_indicators and not has_high_fat

        # Check for high fiber (at least 2 fiber sources)
        fiber_count = sum(
            1 for fiber in self.high_fiber_keywords if fiber in combined_text
        )
        is_high_fiber = fiber_count >= 2

        return {
            "is_high_protein": is_high_protein,
            "is_low_fat": is_low_fat,
            "is_high_fiber": is_high_fiber,
        }

    def extract_metadata(self, title, directions):
        """Extract recipe metadata from title and directions"""
        metadata = {
            "prep_time": None,
            "cook_time": None,
            "servings": None,
            "difficulty_level": "medium",
            "meal_type": "main",
        }

        if pd.isna(directions):
            return metadata

        directions_lower = str(directions).lower()
        title_lower = str(title).lower() if not pd.isna(title) else ""

        # Extract prep time
        prep_match = PREP_TIME_PATTERN.search(directions_lower)
        if prep_match:
            time_val = int(prep_match.group(1))
            if "hour" in prep_match.group(0).lower():
                time_val *= 60
            metadata["prep_time"] = time_val

        # Extract cook time
        cook_match = COOK_TIME_PATTERN.search(directions_lower)
        if cook_match:
            time_val = int(cook_match.group(1))
            if "hour" in cook_match.group(0).lower():
                time_val *= 60
            metadata["cook_time"] = time_val

        # Extract servings
        servings_match = SERVINGS_PATTERN.search(directions_lower)
        if servings_match:
            servings_str = servings_match.group(1)
            if "-" in servings_str:
                # Take average of range
                parts = servings_str.split("-")
                metadata["servings"] = (int(parts[0]) + int(parts[1])) // 2
            else:
                metadata["servings"] = int(servings_str)

        # Determine difficulty level based on directions length and complexity
        num_steps = len(re.findall(r"[.!?]", directions_lower))
        if num_steps < 5:
            metadata["difficulty_level"] = "easy"
        elif num_steps > 15:
            metadata["difficulty_level"] = "hard"

        # Determine meal type
        combined_text = title_lower + " " + directions_lower
        if any(kw in combined_text for kw in self.breakfast_keywords):
            metadata["meal_type"] = "breakfast"
        elif any(kw in combined_text for kw in self.lunch_keywords):
            metadata["meal_type"] = "lunch"
        elif any(kw in combined_text for kw in self.dinner_keywords):
            metadata["meal_type"] = "dinner"
        elif any(kw in combined_text for kw in self.dessert_keywords):
            metadata["meal_type"] = "dessert"
        elif "snack" in combined_text or "appetizer" in combined_text:
            metadata["meal_type"] = "snack"

        return metadata

    def calculate_quality_scores(self, ingredients_clean, directions):
        """Calculate data quality scores"""
        scores = {
            "has_complete_directions": True,
            "ingredient_quality_score": 1.0,
            "recipe_completeness_score": 1.0,
        }

        # Check directions completeness
        if pd.isna(directions) or len(str(directions)) < 50:
            scores["has_complete_directions"] = False
            scores["recipe_completeness_score"] *= 0.5

        # Calculate ingredient quality score
        if ingredients_clean and len(ingredients_clean) > 0:
            # Penalize if too few or too many ingredients
            if len(ingredients_clean) < 3:
                scores["ingredient_quality_score"] *= 0.7
            elif len(ingredients_clean) > 30:
                scores["ingredient_quality_score"] *= 0.8

            # Check for parsing issues
            avg_ingredient_length = sum(len(ing) for ing in ingredients_clean) / len(
                ingredients_clean
            )
            if (
                avg_ingredient_length < 3
            ):  # Very short ingredients suggest parsing issues
                scores["ingredient_quality_score"] *= 0.6
        else:
            scores["ingredient_quality_score"] = 0.0
            scores["recipe_completeness_score"] *= 0.3

        # Overall completeness
        if not directions or not ingredients_clean:
            scores["recipe_completeness_score"] *= 0.3

        return scores

    def process_recipes_batch(self, batch_size=10000, limit=None):
        """Process recipes in batches with enhanced data extraction"""
        print("Starting enhanced recipe processing...")
        start_time = time.time()

        # Get total count
        total_count = self.con.execute("SELECT COUNT(*) FROM raw_recipes").fetchone()[0]
        print(f"Processing {total_count:,} recipes in batches of {batch_size:,}")

        # Calculate total batches
        total_batches = (total_count + batch_size - 1) // batch_size

        # Process in batches
        for batch_num in tqdm(range(total_batches), desc="Processing batches"):
            offset = batch_num * batch_size
            batch_start = time.time()

            # Get batch data
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
            if "ingredients" not in batch_df.columns:
                raise ValueError("'ingredients' column not found in the batch data.")

            # Process ingredients with enhanced cleaning
            use_mp = len(batch_df) > 1000 and batch_size > 1000
            (
                batch_df["ingredients_clean"],
                batch_df["ingredients_original"],
                batch_df["ingredient_quantities"],
                batch_df["ingredient_categories"],
            ) = self.clean_ingredient_string_batch(
                batch_df["ingredients"], use_multiprocessing=use_mp
            )

            batch_df["ingredient_count"] = batch_df["ingredients_clean"].apply(len)

            # Classify dietary restrictions (comprehensive)
            dietary_info = batch_df["ingredients_clean"].apply(
                self.classify_dietary_comprehensive
            )
            batch_df = pd.concat([batch_df, pd.json_normalize(dietary_info)], axis=1)

            # Classify nutritional characteristics
            nutritional_info = batch_df.apply(
                lambda row: self.classify_nutritional(
                    row["ingredients_clean"], row.get("directions", "")
                ),
                axis=1,
            )
            batch_df = pd.concat(
                [batch_df, pd.json_normalize(nutritional_info)], axis=1
            )

            # Extract metadata
            metadata_info = batch_df.apply(
                lambda row: self.extract_metadata(
                    row.get("title", ""), row.get("directions", "")
                ),
                axis=1,
            )
            batch_df = pd.concat([batch_df, pd.json_normalize(metadata_info)], axis=1)

            # Calculate quality scores
            quality_info = batch_df.apply(
                lambda row: self.calculate_quality_scores(
                    row["ingredients_clean"], row.get("directions", "")
                ),
                axis=1,
            )
            batch_df = pd.concat([batch_df, pd.json_normalize(quality_info)], axis=1)

            # Create search text for full-text search
            batch_df["search_text"] = batch_df.apply(
                lambda row: f"{row.get('title', '')} {' '.join(row['ingredients_clean'])}".lower(),
                axis=1,
            )

            # Calculate total time if not already present
            if "total_time" not in batch_df.columns:
                batch_df["total_time"] = batch_df.apply(
                    lambda row: (row.get("prep_time", 0) or 0)
                    + (row.get("cook_time", 0) or 0)
                    if row.get("prep_time") or row.get("cook_time")
                    else None,
                    axis=1,
                )

            # Prepare data for insertion
            if "id" in batch_df.columns:
                batch_df = batch_df.rename(columns={"id": "recipe_id"})
            elif "row_id" in batch_df.columns:
                batch_df = batch_df.rename(columns={"row_id": "recipe_id"})
            else:
                batch_df["recipe_id"] = range(offset + 1, offset + 1 + len(batch_df))

            # Handle missing values
            batch_df["rating"] = pd.to_numeric(batch_df.get("rating"), errors="coerce")
            batch_df["cuisine_type"] = batch_df.get("cuisine_type", "")

            # Insert batch
            try:
                # List all columns we want to insert
                cols_to_insert = [
                    "recipe_id",
                    "title",
                    "ingredients",
                    "directions",
                    "prep_time",
                    "cook_time",
                    "total_time",
                    "servings",
                    "difficulty_level",
                    "meal_type",
                    "ingredients_clean",
                    "ingredients_original",
                    "ingredient_quantities",
                    "ingredient_categories",
                    "ingredient_count",
                    "is_vegetarian",
                    "is_vegan",
                    "is_gluten_free",
                    "is_dairy_free",
                    "is_nut_free",
                    "is_low_carb",
                    "is_dessert",
                    "is_high_protein",
                    "is_low_fat",
                    "is_high_fiber",
                    "has_complete_directions",
                    "ingredient_quality_score",
                    "recipe_completeness_score",
                    "search_text",
                ]

                # Add optional columns if they exist
                if "rating" in batch_df.columns:
                    cols_to_insert.insert(4, "rating")
                if "cuisine_type" in batch_df.columns:
                    cols_to_insert.insert(10, "cuisine_type")

                # Filter to only include columns that exist
                cols_to_insert = [
                    col for col in cols_to_insert if col in batch_df.columns
                ]

                self.con.register("temp_batch", batch_df[cols_to_insert])

                # Build column list for insert
                insert_cols = ", ".join(cols_to_insert)

                # Use INSERT OR REPLACE to handle duplicates
                self.con.execute(f"""
                    INSERT OR REPLACE INTO recipes ({insert_cols})
                    SELECT {insert_cols} FROM temp_batch
                """)

                # Commit after each batch
                self.con.commit()

                batch_time = time.time() - batch_start
                items_per_sec = len(batch_df) / batch_time if batch_time > 0 else 0

                print(
                    f"\nProcessed batch {batch_num + 1}/{total_batches} "
                    f"({len(batch_df):,} items, {items_per_sec:.1f} items/sec)"
                )

            except Exception as e:
                print(f"\nError processing batch {batch_num + 1}: {str(e)}")
                self._process_failed_batch(batch_df)

            # Clean up memory
            del batch_df
            gc.collect()

        total_time = time.time() - start_time
        print(f"\nProcessing complete! Total time: {total_time / 60:.1f} minutes")
        print(f"Average speed: {total_count / total_time:.1f} items/second")

    def _process_failed_batch(self, batch_df):
        """Process individual records if batch insert fails"""
        success = 0
        for _, row in tqdm(
            batch_df.iterrows(), total=len(batch_df), desc="Processing failed batch"
        ):
            try:
                # Build a simplified insert for failed records
                self.con.execute(
                    """
                    INSERT OR REPLACE INTO recipes (
                        recipe_id, title, ingredients, directions,
                        ingredients_clean, ingredient_count,
                        is_vegetarian, is_vegan, is_dessert
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        row.get("recipe_id"),
                        row.get("title", ""),
                        row.get("ingredients", ""),
                        row.get("directions", ""),
                        row.get("ingredients_clean", []),
                        row.get("ingredient_count", 0),
                        row.get("is_vegetarian", False),
                        row.get("is_vegan", False),
                        row.get("is_dessert", False),
                    ],
                )
                success += 1
            except Exception as e:
                print(f"Error inserting recipe {row.get('recipe_id')}: {e}")

        if success < len(batch_df):
            print(f"Warning: Only {success} of {len(batch_df)} records were processed")

    def get_statistics(self):
        """Get comprehensive statistics using DuckDB"""
        stats = self.con.execute("""
            SELECT 
                COUNT(*) as total_recipes,
                SUM(CASE WHEN is_vegetarian THEN 1 ELSE 0 END) as vegetarian_count,
                SUM(CASE WHEN is_vegan THEN 1 ELSE 0 END) as vegan_count,
                SUM(CASE WHEN is_gluten_free THEN 1 ELSE 0 END) as gluten_free_count,
                SUM(CASE WHEN is_dairy_free THEN 1 ELSE 0 END) as dairy_free_count,
                SUM(CASE WHEN is_nut_free THEN 1 ELSE 0 END) as nut_free_count,
                SUM(CASE WHEN is_low_carb THEN 1 ELSE 0 END) as low_carb_count,
                SUM(CASE WHEN is_dessert THEN 1 ELSE 0 END) as dessert_count,
                SUM(CASE WHEN is_high_protein THEN 1 ELSE 0 END) as high_protein_count,
                SUM(CASE WHEN is_low_fat THEN 1 ELSE 0 END) as low_fat_count,
                SUM(CASE WHEN is_high_fiber THEN 1 ELSE 0 END) as high_fiber_count,
                AVG(ingredient_count) as avg_ingredient_count,
                AVG(total_time) as avg_total_time,
                AVG(ingredient_quality_score) as avg_quality_score,
                SUM(CASE WHEN has_complete_directions THEN 1 ELSE 0 END) as complete_directions_count
            FROM recipes
        """).fetchone()

        return {
            "total_recipes": stats[0] or 0,
            "vegetarian_count": stats[1] or 0,
            "vegan_count": stats[2] or 0,
            "gluten_free_count": stats[3] or 0,
            "dairy_free_count": stats[4] or 0,
            "nut_free_count": stats[5] or 0,
            "low_carb_count": stats[6] or 0,
            "dessert_count": stats[7] or 0,
            "high_protein_count": stats[8] or 0,
            "low_fat_count": stats[9] or 0,
            "high_fiber_count": stats[10] or 0,
            "avg_ingredient_count": stats[11] or 0,
            "avg_total_time": stats[12] or 0,
            "avg_quality_score": stats[13] or 0,
            "complete_directions_count": stats[14] or 0,
        }

    def validate_classifications(self, sample_size=20):
        """Validate dietary classifications by sampling"""
        print("\n=== Validating Classifications ===")

        # Get samples of vegetarian recipes
        vegetarian_sample = self.con.execute(f"""
            SELECT title, ingredients_clean
            FROM recipes 
            WHERE is_vegetarian = true
            ORDER BY RANDOM()
            LIMIT {sample_size}
        """).fetchdf()

        if not vegetarian_sample.empty:
            print("\nSample vegetarian recipes:")
            for idx, row in vegetarian_sample.head(5).iterrows():
                print(f"- {row['title']}")
                if len(row["ingredients_clean"]) > 0:
                    print(
                        f"  Ingredients: {', '.join(row['ingredients_clean'][:5])}..."
                    )

        # Get samples of gluten-free recipes
        gluten_free_sample = self.con.execute("""
            SELECT title, ingredients_clean
            FROM recipes 
            WHERE is_gluten_free = true
            ORDER BY RANDOM()
            LIMIT 5
        """).fetchdf()

        if not gluten_free_sample.empty:
            print("\nSample gluten-free recipes:")
            for idx, row in gluten_free_sample.iterrows():
                print(f"- {row['title']}")

        # Get high-quality recipes
        high_quality_sample = self.con.execute("""
            SELECT title, recipe_completeness_score, ingredient_quality_score
            FROM recipes 
            WHERE recipe_completeness_score > 0.8
            ORDER BY recipe_completeness_score DESC
            LIMIT 5
        """).fetchdf()

        if not high_quality_sample.empty:
            print("\nHighest quality recipes:")
            for idx, row in high_quality_sample.iterrows():
                print(
                    f"- {row['title']} (Quality: {row['recipe_completeness_score']:.2f})"
                )


# Usage example
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Enhanced recipe data processor with nutritional analysis."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Number of recipes to process in each batch (default: 10000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of recipes to process (default: None, process all)",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default=None,
        help="Path to the CSV file (default: full_dataset.csv in the same directory)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the output database (default: data/recipes.db)",
    )
    parser.add_argument(
        "--validate",
        type=int,
        default=10,
        help="Number of samples to validate (default: 10, set to 0 to skip)",
    )
    return parser.parse_args()


def main():
    try:
        args = parse_arguments()

        # Set up database path
        if args.db_path is None:
            import os

            db_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
            )
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "recipes.db")
        else:
            db_path = args.db_path

        # Initialize processor
        print(f"Initializing enhanced processor with database: {db_path}")
        processor = EnhancedRecipeProcessor(db_path=db_path)

        # Set up CSV path
        if args.csv_path is None:
            import os

            csv_path = os.path.join(os.path.dirname(__file__), "full_dataset.csv")
        else:
            csv_path = args.csv_path

        print(f"Loading data from {csv_path}...")
        processor.load_data_from_csv(csv_path, limit=args.limit)

        # Process recipes
        print("\nStarting enhanced batch processing...")
        start_time = time.time()

        print(
            f"Processing {'all recipes' if args.limit is None else f'up to {args.limit:,} recipes'} "
            f"in batches of {args.batch_size:,}"
        )

        processor.process_recipes_batch(batch_size=args.batch_size, limit=args.limit)

        # Get and display statistics
        print("\nGenerating enhanced statistics...")
        stats = processor.get_statistics()

        print("\n=== Enhanced Processing Statistics ===")
        print("\n--- Recipe Counts ---")
        print(f"Total recipes: {stats['total_recipes']:,}")
        print(f"Complete directions: {stats['complete_directions_count']:,}")

        print("\n--- Dietary Classifications ---")
        for diet in [
            "vegetarian",
            "vegan",
            "gluten_free",
            "dairy_free",
            "nut_free",
            "low_carb",
            "dessert",
        ]:
            key = f"{diet}_count"
            if key in stats:
                percentage = (
                    (stats[key] / stats["total_recipes"] * 100)
                    if stats["total_recipes"] > 0
                    else 0
                )
                print(
                    f"{diet.replace('_', ' ').title()}: {stats[key]:,} ({percentage:.1f}%)"
                )

        print("\n--- Nutritional Indicators ---")
        for nutrition in ["high_protein", "low_fat", "high_fiber"]:
            key = f"{nutrition}_count"
            if key in stats:
                percentage = (
                    (stats[key] / stats["total_recipes"] * 100)
                    if stats["total_recipes"] > 0
                    else 0
                )
                print(
                    f"{nutrition.replace('_', ' ').title()}: {stats[key]:,} ({percentage:.1f}%)"
                )

        print("\n--- Averages ---")
        print(f"Avg ingredients per recipe: {stats['avg_ingredient_count']:.1f}")
        print(
            f"Avg total time (minutes): {stats['avg_total_time']:.1f}"
            if stats["avg_total_time"]
            else "Avg total time: N/A"
        )
        print(f"Avg quality score: {stats['avg_quality_score']:.2f}")

        # Validate if requested
        if args.validate > 0:
            print(f"\nValidating classifications ({args.validate} samples)...")
            processor.validate_classifications(sample_size=args.validate)

        total_time = (time.time() - start_time) / 60
        print("\n=== Enhanced Processing Complete! ===")
        print(f"Total processing time: {total_time:.1f} minutes")
        print(
            f"Average speed: {stats['total_recipes'] / (total_time * 60):.1f} recipes/second"
        )

    except Exception as e:
        print(f"\nError during processing: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
