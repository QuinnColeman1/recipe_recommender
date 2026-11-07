# Recipe Recommender

An intelligent recipe recommendation system that helps you discover new recipes based on ingredients you have, dietary preferences, and cooking time constraints.

## Features

- **Advanced Search**: Find recipes by ingredients, dietary needs, or text search
- **Smart Filters**: Filter by meal type, cooking time, difficulty, and more
- **Dietary Analysis**: Automatic detection of vegetarian, vegan, gluten-free, and other dietary attributes
- **Rich Recipe Cards**: Beautifully formatted recipe cards with nutritional information
- **Save Favorites**: Save your favorite recipes for later
- **Responsive Design**: Works on desktop and mobile devices

## Project Structure

```
recipe-recommender/
├── data/                    # Data files and processing
│   ├── __init__.py
│   ├── data_processor.py    # Streams the CSV through the cleaning rules into DuckDB
│   ├── cleaning.py          # Cleaning rules (ingredients, times, labels, meal types)
│   ├── full_dataset.csv     # Raw dataset (not versioned, see below for sources)
│   ├── build_app_db.py      # Builds the lean, search-indexed app database
│   ├── recipes.db           # Full processed DuckDB database (generated)
│   └── recipes_app.db       # Lean database the app reads (generated)
├── recipe_app/              # Web interface
│   ├── __init__.py
│   ├── streamlit_app.py     # Main Streamlit application
│   ├── ui_helpers.py        # Formatting helpers for the UI
│   └── main.py              # Search logic (DuckDB queries)
├── tests/                   # Unit tests
│   ├── conftest.py          # Builds a tiny test database
│   ├── test_main.py         # Search logic tests
│   ├── test_cleaning.py     # Cleaning rule tests
│   ├── test_data_processor.py  # CSV -> database -> app end-to-end test
│   └── test_streamlit_helpers.py
├── .gitignore
├── Makefile                 # Project automation
├── pyproject.toml           # Project metadata and dependencies
└── README.md                # This file
```

## Dataset

### Recommended Datasets

1. **RecipeNLG** (2M+ recipes)
   - Source: [Kaggle](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews)
   - Size: ~2.3M recipes
   - Format: CSV with title, ingredients, directions, etc.
   - Notes: Well-structured with clean data

2. **Recipe1M+**
   - Source: [MIT Computer Science](http://pic2recipe.csail.mit.edu/)
   - Size: 1M+ recipes with images
   - Format: JSON
   - Notes: Includes image data but requires more preprocessing

3. **Reddit r/recipes**
   - Source: [Pushshift](https://files.pushshift.io/reddit/datasets/)
   - Size: Varies
   - Notes: Community-sourced recipes, may require more cleaning

### Data Format

Place your dataset in `data/full_dataset.csv` with these recommended columns:
- `title`: Recipe name
- `ingredients`: List of ingredients (one per line or comma-separated)
- `directions`: Cooking instructions
- `prep_time`: Preparation time in minutes (optional)
- `cook_time`: Cooking time in minutes (optional)
- `servings`: Number of servings (optional)

## Setup

### Prerequisites

- Python 3.10+
- Poetry (for dependency management)
- 8GB+ RAM recommended for processing large datasets

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/recipe-recommender.git
   cd recipe-recommender
   ```

2. **Install dependencies**
   ```bash
   poetry install
   ```

3. **Download dataset**
   - Download a dataset (e.g., from Kaggle)
   - Place it at `data/full_dataset.csv`

4. **Process the data**
   ```bash
   # Full dataset (about 10-15 minutes, under 1 GB of RAM)
   poetry run python -m data.data_processor

   # Quick development run on a subset
   poetry run python -m data.data_processor --limit 10000 --db-path data/recipes_dev.db
   ```
   Cleaning rules live in `data/cleaning.py`:
   - ingredient names come from the dataset's `NER` column, with a fallback
     parser for lines `NER` missed (so e.g. "1 1/2 lb. round steak" still counts)
   - cooking times are estimated from durations written in the directions
   - dietary labels use whole-word matching with exceptions (eggplant, peanut
     butter, coconut milk, butternut squash, ...)
   - meal type comes from the title, falling back to the ingredients
   - duplicate recipes (same title and ingredients) are removed

   The processor refuses to overwrite an existing database unless you pass
   `--overwrite`.

5. **Build the app database**
   ```bash
   poetry run python -m data.build_app_db   # or: make app-db
   # from another database:
   poetry run python -m data.build_app_db --source data/recipes_dev.db --output data/recipes_app_dev.db
   ```
   This copies only the columns the app uses from `data/recipes.db` into
   `data/recipes_app.db` and adds an ingredient lookup index (about 1 minute
   and under 3 GB of RAM for the full 2.2M recipes). After this, the app only
   needs `recipes_app.db`; `recipes.db` and `full_dataset.csv` can be archived.

6. **Launch the application**
   ```bash
   poetry run streamlit run recipe_app/streamlit_app.py

   # or point the app at a different app database:
   RECIPE_DB=data/recipes_app_dev.db poetry run streamlit run recipe_app/streamlit_app.py
   ```
   The app will be available at [http://localhost:8501](http://localhost:8501)

## Development

### Makefile Commands

```bash
# Format code
make format

# Run linting
make lint

# Run tests
make test

# Process data (first 10k rows)
make process-data

# Clean up temporary files
make clean
```

### Adding New Features

1. Create a new branch
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and test them

3. Run tests and linting
   ```bash
   make test
   make lint
   ```

4. Commit and push your changes
   ```bash
   git add .
   git commit -m "Add your feature"
   git push origin feature/your-feature-name
   ```

## Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- RecipeNLG dataset for providing a comprehensive recipe collection
- Streamlit for the amazing web framework
- DuckDB for high-performance data processing
