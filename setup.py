from setuptools import setup, find_packages

setup(
    name="recipe_recommender",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pandas>=2.3.1",
        "scikit-learn>=1.7.1",
        "streamlit>=1.47.1",
        "duckdb>=1.3.2",
        "plotly>=5.18.0",
    ],
    python_requires=">=3.11",
)
