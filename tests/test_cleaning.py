"""Tests for data/cleaning.py, built from real problem rows in the dataset."""

import json

import pytest

from data.cleaning import (
    build_ingredients,
    categorize_ingredient,
    classify_diet,
    classify_difficulty,
    classify_meal_type,
    clean_title,
    extract_quantity,
    extract_servings,
    extract_times,
    name_from_line,
    normalize_name,
    parse_list_field,
    process_record,
    quality_score,
    to_number,
)


def record(title, lines, ner=None, directions=("Mix well.",)):
    return process_record(
        {
            "title": title,
            "ingredients": json.dumps(list(lines)),
            "ner": json.dumps(list(ner if ner is not None else [])),
            "directions": json.dumps(list(directions)),
        }
    )


# ---------------------------------------------------------------- parsing


def test_parse_list_field_json_keeps_commas_inside_items():
    value = '["1 small jar pimiento, chopped and drained", "1/2 c. pecans"]'
    assert parse_list_field(value) == [
        "1 small jar pimiento, chopped and drained",
        "1/2 c. pecans",
    ]


def test_parse_list_field_plain_text():
    assert parse_list_field("eggs\nmilk\n\nflour") == ["eggs", "milk", "flour"]
    assert parse_list_field(None) == []
    assert parse_list_field("nan") == []


@pytest.mark.parametrize(
    "line, quantity",
    [
        ("3/4 c. sugar", "3/4 c."),
        ("1 (12 oz.) box Crispix cereal", "1 (12 oz.) box"),
        ("1 1/2 Tbsp. onion juice", "1 1/2 Tbsp."),
        ("2-3 cloves garlic", "2-3 cloves"),
        ("salt to taste", None),
    ],
)
def test_extract_quantity(line, quantity):
    assert extract_quantity(line) == quantity


@pytest.mark.parametrize(
    "line, name",
    [
        ("1 1/2 lb. round steak", "round steak"),
        ("8 oz. spaghetti, broken, cooked and drained", "spaghetti"),
        ("4 (4 oz.) skinless, boneless chicken breasts", "chicken breasts"),
        ("20 spears cooked asparagus (fresh or canned)", "asparagus"),
        ("2 8 inch pie shells", "pie shells"),
        ("1 tsp. Beau Monde seasoning", "beau monde seasoning"),
        ("1/4 orange - squeeze juice ONLY-approximately", "orange"),
        ("several shakes Tabasco", "tabasco"),
        ("desired seasonings", None),
        ("Filling:", None),
    ],
)
def test_name_from_line(line, name):
    assert name_from_line(line) == name


def test_normalize_name_keeps_plurals_intact():
    # The old cleaner produced "noodl", "chees" and "molass".
    assert normalize_name("Noodles") == "noodles"
    assert normalize_name("Cheese") == "cheese"
    assert normalize_name("molasses") == "molasses"


def test_normalize_name_drops_descriptors_and_junk():
    assert normalize_name("chopped spinach") == "spinach"
    assert normalize_name("clove garlic") == "garlic"
    assert normalize_name("skinless") is None
    assert normalize_name("choice") is None


def test_build_ingredients_recovers_lines_ner_missed():
    lines = [
        "1/4 c. lemon juice",
        "1 large can asparagus, chopped",
        "4 (4 oz.) skinless, boneless chicken breasts",
    ]
    names, quantities, coverage = build_ingredients(lines, ["lemon juice", "skinless"])
    assert names == ["lemon juice", "asparagus", "chicken breasts"]
    assert quantities == ["1/4 c.", "1", "4 (4 oz.)"]
    assert coverage == 1.0


@pytest.mark.parametrize(
    "name, category",
    [
        ("black pepper", "herbs_spices"),
        ("green pepper", "vegetable"),
        ("peanut butter", "nuts_seeds"),
        ("eggplant", "vegetable"),
        ("butter", "dairy"),
        ("chicken broth", "other"),
        ("cheddar cheese", "dairy"),
        ("pineapple", "fruit"),
    ],
)
def test_categorize_ingredient(name, category):
    assert categorize_ingredient(name) == category


# ---------------------------------------------------------------- labels


@pytest.mark.parametrize(
    "lines, flag, expected",
    [
        (["1 eggplant", "2 tbsp. olive oil"], "is_vegan", True),
        (["1 c. peanut butter", "1 c. sugar"], "is_dairy_free", True),
        (["1 can coconut milk", "1 c. rice"], "is_dairy_free", True),
        (["1 butternut squash", "1 tsp. nutmeg"], "is_nut_free", True),
        (["1 c. chopped nuts"], "is_nut_free", False),
        (["1 c. graham cracker crumbs"], "is_vegetarian", True),
        (["1 lb. ground round"], "is_vegetarian", False),
        (["1 envelope gelatin"], "is_vegetarian", False),
        (["2 tbsp. honey"], "is_vegan", False),
        (["2 c. almond flour", "2 eggs"], "is_gluten_free", True),
        (["2 c. flour"], "is_gluten_free", False),
        (["1 can cream of mushroom soup"], "is_gluten_free", False),
        (["2 c. green beans", "1 tsp. salt"], "is_low_carb", True),
        (["1 c. rice"], "is_low_carb", False),
    ],
)
def test_dietary_flags(lines, flag, expected):
    text = " | ".join(line.lower() for line in lines)
    assert classify_diet(text, "", is_dessert=False)[flag] is expected


def test_broth_does_not_make_a_dish_high_protein():
    text = "2 c. chicken broth | 1 c. rice | 1 onion"
    flags = classify_diet(text, "", is_dessert=False)
    assert flags["is_vegetarian"] is False
    assert flags["is_high_protein"] is False


def test_meat_line_missing_from_ner_is_still_seen():
    r = record("Swiss Steak", ["1 1/2 lb. round steak", "1 c. flour"], ner=["flour"])
    assert "round steak" in r["ingredients_clean"]
    assert r["is_vegetarian"] is False


@pytest.mark.parametrize(
    "title, meal",
    [
        ("Blueberry Pancakes", "breakfast"),
        ("Coffee Cake", "breakfast"),
        ("Chocolate Cake", "dessert"),
        ("Crab Cakes", "dinner"),
        ("Chicken Pot Pie", "dinner"),
        ("Pecan Pie", "dessert"),
        ("Poppy Seed Dressing", "side"),
        ("Barbecue Sauce", "side"),
        ("Broccoli Cheese Soup", "lunch"),
        ("Spinach Dip", "snack"),
        ("Hot Spiced Cider", "drink"),
        ("Zucchini Bread", "side"),
        ("Beef Stroganoff", "dinner"),
    ],
)
def test_meal_type_from_title(title, meal):
    assert classify_meal_type(title, "", has_meat=False) == meal


def test_meal_type_falls_back_to_ingredients():
    sweet = "sugar | cocoa | vanilla | butter"
    assert classify_meal_type("Grandma's Special", sweet, has_meat=False) == "dessert"
    assert (
        classify_meal_type("Grandma's Special", "beef | onion", has_meat=True)
        == "dinner"
    )
    assert (
        classify_meal_type(
            "Caribbean Breeze", "light rum | pineapple juice", has_meat=False
        )
        == "drink"
    )


def test_eggs_in_directions_no_longer_mean_breakfast():
    r = record(
        "Lemon Bars",
        ["2 c. flour", "4 eggs", "2 c. sugar"],
        ner=["flour", "eggs", "sugar"],
        directions=["Beat eggs with sugar.", "Bake at 350 for 25 minutes."],
    )
    assert r["meal_type"] == "dessert"


# ---------------------------------------------------------------- times etc.


def test_extract_times_sums_durations_and_takes_range_maximum():
    steps = [
        "Simmer the water, lentils and salt for 15 to 20 minutes.",
        "Stir-fry carrots in hot oil for 2 minutes.",
        "Chill 1 hour.",
    ]
    assert extract_times(steps) == {
        "prep_time": None,
        "cook_time": 22,
        "total_time": 82,
    }


def test_extract_times_ignores_repeats_and_per_pound():
    steps = [
        "Bake for 1 hour, stirring every 15 minutes.",
        "Roast 20 minutes per pound.",
    ]
    assert extract_times(steps)["total_time"] == 60


def test_extract_times_words_and_overnight():
    assert (
        extract_times(["Bake about an hour and a half hour more."])["total_time"] == 90
    )
    assert extract_times(["Refrigerate overnight."])["total_time"] == 480
    assert extract_times(["Mix and serve."])["total_time"] is None


@pytest.mark.parametrize(
    "title, steps, servings",
    [
        ("Asparagus Aspic", ["Refrigerate. Serves 6 to 8."], 7),
        ("Parmesan Chicken Cutlets(Makes 4 Servings)  ", ["Bake."], 4),
        ("Cookies", ["Makes 3 dozen cookies."], None),
        ("Stew", ["Makes 6."], 6),
    ],
)
def test_extract_servings(title, steps, servings):
    assert extract_servings(title, steps) == servings


def test_clean_title():
    assert (
        clean_title("Parmesan Chicken Cutlets(Makes 4 Servings)  ")
        == "Parmesan Chicken Cutlets"
    )
    assert clean_title("Rati Mum'S Special Chicken") == "Rati Mum's Special Chicken"
    assert clean_title(None) == ""


def test_quality_score_spreads_and_penalises_junk():
    good = record(
        "Beef Stew",
        ["2 lb. beef", "4 potatoes", "3 carrots", "1 onion"],
        ner=["beef", "potatoes", "carrots", "onion"],
        directions=[
            "Brown the beef in a large pot for 10 minutes.",
            "Add vegetables and water; simmer 2 hours until tender. Serves 6.",
        ],
    )
    thin = record("Toast", ["1 slice bread"], ner=["bread"], directions=["Toast it."])
    hint = record(
        "Hint: For Crisp Curtains",
        ["1 c. sugar"],
        ner=["sugar"],
        directions=["Rinse curtains in sugar water."],
    )
    assert good["recipe_completeness_score"] > 0.75
    assert thin["recipe_completeness_score"] < good["recipe_completeness_score"] - 0.2
    assert hint["recipe_completeness_score"] < 0.3


def test_process_record_directions_and_link():
    r = process_record(
        {
            "title": "Coconut Pies",
            "ingredients": '["1/2 stick oleo", "2 c. coconut"]',
            "ner": '["oleo", "coconut"]',
            "directions": '["Melt oleo.", "Bake at 350\\u00b0 until browned."]',
            "link": "www.cookbooks.com/Recipe-Details.aspx?id=983970",
            "source": "Gathered",
        }
    )
    assert r["directions"] == "Melt oleo.\nBake at 350° until browned."
    assert r["link"] == "https://www.cookbooks.com/Recipe-Details.aspx?id=983970"
    assert r["ingredient_quantities"] == ["1/2 stick", "2 c."]
    assert "coconut pies" in r["search_text"]


def test_extract_times_adds_estimated_prep():
    # "cook 1 minute" in a 10-ingredient recipe is not a 1-minute recipe
    times = extract_times(["Cook 1 minute."], ingredient_count=10)
    assert times == {"prep_time": 15, "cook_time": 1, "total_time": 16}
    assert extract_times(["Prep time: 5 minutes. Cook 1 minute."], 10)["prep_time"] == 5
    assert extract_times(["Mix and serve."], 10)["total_time"] is None


# ---------------------------------------------------------------- edge cases


def test_parse_list_field_other_inputs():
    assert parse_list_field(["a ", None, " b"]) == ["a", "b"]
    assert parse_list_field("salt; pepper") == ["salt", "pepper"]
    assert parse_list_field("[not json") == ["[not json"]
    assert parse_list_field('"just a string"') == ['"just a string"']


@pytest.mark.parametrize(
    "text, value",
    [
        ("1 1/2", 1.5),
        ("3/4", 0.75),
        ("½", 0.5),
        ("an", 1),
        ("half an", 0.5),
        ("2.5", 2.5),
        ("1/0", None),
        ("abc", None),
    ],
)
def test_to_number(text, value):
    assert to_number(text) == value


def test_extract_times_hours_and_explicit_prep_in_hours():
    assert extract_times(["Bake 1 1/2 hours."])["cook_time"] == 90
    times = extract_times(["Prep time: 1 hour.", "Bake 30 minutes."], 5)
    assert times["prep_time"] == 60 and times["total_time"] == 90


def test_extract_times_ignores_absurd_durations():
    assert extract_times(["Age the cheese for 500 hours."])["total_time"] is None


def test_classify_difficulty_levels():
    easy = classify_difficulty(["Mix.", "Serve."], 3, 10, "")
    hard = classify_difficulty(
        ["Dissolve yeast. Knead 10 minutes. Let rise. Roll out dough."] * 4,
        18,
        180,
        "yeast knead let rise roll out",
    )
    medium = classify_difficulty(["Mix. Stir. Pour. Bake. Cool. Cut."], 10, 50, "")
    assert (easy, medium, hard) == ("easy", "medium", "hard")


def test_quality_score_ingredient_edges():
    steps = ["Mix everything together well and bake until golden brown on top."] * 4
    assert quality_score("Thing", steps, 0, 0.0, False, False) < quality_score(
        "Thing", steps, 30, 1.0, False, False
    )
    assert quality_score("Thing", steps, 30, 1.0, False, False) < quality_score(
        "Thing", steps, 10, 1.0, False, False
    )


def test_meal_type_other_and_clean_title_nan():
    assert (
        classify_meal_type("Grandma's Special", "water | salt", has_meat=False)
        == "other"
    )
    assert clean_title("nan") == ""


def test_normalize_name_edge_cases():
    assert normalize_name("  ") is None
    assert normalize_name("1/2") is None
    assert normalize_name("of the salt and") == "salt"
