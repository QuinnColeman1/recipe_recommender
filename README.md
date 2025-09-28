# Recipe Recommender Pro

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
│   ├── data_processor.py    # Data processing and DuckDB integration
│   ├── full_dataset.csv     # Raw dataset (not versioned, see below for sources)
│   └── recipes.db           # Processed SQLite database (generated)
├── streamlit/               # Web interface
│   ├── __init__.py
│   ├── streamlit_app.py     # Main Streamlit application
│   └── main.py              # Core application logic
├── tests/                   # Unit and integration tests
│   ├── __init__.py
│   └── test_data.py         # Test cases for data processing
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
   # Process with default settings (may take 10-30 minutes for large datasets)
   poetry run python -m data.data_processor
   
   # For large datasets, you can process a subset first:
   poetry run python -m data.data_processor --limit 10000
   ```

5. **Launch the application**
   ```bash
   poetry run streamlit run streamlit/streamlit_app.py
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
