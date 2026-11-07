"""
Pure functions that turn one raw recipe row into clean, searchable fields.

Kept free of pandas/DuckDB so they are easy to unit test and cheap to run in
worker processes. ``process_record`` is the entry point used by
``data_processor.py``.

Designed for the RecipeNLG CSV (columns: title, ingredients, directions, NER,
link, source), where ``ingredients``/``directions``/``NER`` are JSON lists.
Plain-text columns (one item per line or comma-separated) also work.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------


def _words_re(words: Iterable[str], plural: bool = True) -> re.Pattern:
    """Whole-word regex for any of ``words`` (optionally allowing s/es plurals)."""
    suffix = r"(?:e?s)?" if plural else ""
    alts = sorted({re.escape(w) for w in words}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(alts) + r")" + suffix + r"\b")


def _phrases_re(phrases: Iterable[str]) -> re.Pattern:
    """Regex matching any of ``phrases`` (regex syntax allowed), as whole words."""
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b")


WHITESPACE = re.compile(r"\s+")


def _squash(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip()


def parse_list_field(value: Any) -> List[str]:
    """Parse a JSON list column; fall back to newline/semicolon/comma splitting."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value if v is not None]
    else:
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return []
        try:
            parsed = json.loads(text)
            items = [str(v) for v in parsed] if isinstance(parsed, list) else [text]
        except ValueError:
            for sep in ("\n", ";", ","):
                if sep in text:
                    items = text.split(sep)
                    break
            else:
                items = [text]
    return [_squash(item) for item in items if item and _squash(item)]


# --------------------------------------------------------------------------
# Numbers, quantities and units
# --------------------------------------------------------------------------

UNICODE_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "sixty": 60,
    "half an": 0.5,
    "half a": 0.5,
    "a half": 0.5,
}
_NUM_DIGITS = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛]"
_NUM_ANY = (
    _NUM_DIGITS
    + "|"
    + "|".join(sorted((re.escape(w) for w in WORD_NUMBERS), key=len, reverse=True))
)


def to_number(text: str) -> Optional[float]:
    text = text.strip().lower()
    if text in WORD_NUMBERS:
        return float(WORD_NUMBERS[text])
    if text in UNICODE_FRACTIONS:
        return UNICODE_FRACTIONS[text]
    try:
        if " " in text and "/" in text:
            whole, frac = text.split(None, 1)
            num, den = frac.split("/")
            return float(whole) + float(num) / float(den)
        if "/" in text:
            num, den = text.split("/")
            return float(num) / float(den)
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


UNIT_WORDS = [
    "c",
    "cup",
    "cups",
    "tbsp",
    "tbs",
    "tbl",
    "tbsps",
    "tablespoon",
    "tablespoons",
    "t",
    "tsp",
    "tsps",
    "teaspoon",
    "teaspoons",
    "oz",
    "ounce",
    "ounces",
    "fl",
    "lb",
    "lbs",
    "pound",
    "pounds",
    "g",
    "gram",
    "grams",
    "kg",
    "ml",
    "l",
    "liter",
    "liters",
    "litre",
    "litres",
    "qt",
    "qts",
    "quart",
    "quarts",
    "pt",
    "pts",
    "pint",
    "pints",
    "gal",
    "gallon",
    "gallons",
    "pkg",
    "pkgs",
    "pk",
    "package",
    "packages",
    "packet",
    "packets",
    "can",
    "cans",
    "jar",
    "jars",
    "box",
    "boxes",
    "bag",
    "bags",
    "envelope",
    "envelopes",
    "container",
    "containers",
    "carton",
    "cartons",
    "bottle",
    "bottles",
    "tub",
    "stick",
    "sticks",
    "slice",
    "slices",
    "piece",
    "pieces",
    "clove",
    "cloves",
    "head",
    "heads",
    "stalk",
    "stalks",
    "rib",
    "ribs",
    "bunch",
    "bunches",
    "sprig",
    "sprigs",
    "dash",
    "dashes",
    "pinch",
    "pinches",
    "drop",
    "drops",
    "handful",
    "handfuls",
    "square",
    "squares",
    "spear",
    "spears",
    "shake",
    "shakes",
    "loaf",
    "loaves",
    "scoop",
    "scoops",
    "sheet",
    "sheets",
    "strip",
    "strips",
    "lg",
    "sm",
    "med",
    "doz",
    "dozen",
]
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNIT_WORDS), key=len, reverse=True))
UNIT_SET = set(UNIT_WORDS)

LEADING_QUANTITY = re.compile(
    rf"^\s*(?:about\s+|approx\.?\s+)?"
    rf"((?:{_NUM_DIGITS})(?:\s*(?:-|to)\s*(?:{_NUM_DIGITS}))?"
    rf"(?:\s*\([^)]*\))?"
    rf"(?:\s*(?:{_UNIT_ALT})\b\.?)?)",
    re.IGNORECASE,
)


def extract_quantity(line: str) -> Optional[str]:
    """The leading amount of an ingredient line, e.g. '1 (12 oz.) box' or '3/4 c.'."""
    match = LEADING_QUANTITY.match(line)
    return _squash(match.group(1)) if match else None


# --------------------------------------------------------------------------
# Ingredient names
# --------------------------------------------------------------------------

DESCRIPTOR_WORDS = {
    "chopped",
    "diced",
    "sliced",
    "minced",
    "crushed",
    "grated",
    "shredded",
    "melted",
    "softened",
    "fresh",
    "freshly",
    "frozen",
    "thawed",
    "canned",
    "drained",
    "undrained",
    "rinsed",
    "peeled",
    "seeded",
    "cored",
    "cubed",
    "halved",
    "quartered",
    "beaten",
    "sifted",
    "packed",
    "firmly",
    "lightly",
    "finely",
    "coarsely",
    "thinly",
    "roughly",
    "cooked",
    "uncooked",
    "raw",
    "boiled",
    "toasted",
    "divided",
    "optional",
    "large",
    "small",
    "medium",
    "extra",
    "jumbo",
    "whole",
    "skinless",
    "boneless",
    "room",
    "temperature",
    "warm",
    "hot",
    "cold",
    "boiling",
    "lukewarm",
    "heaping",
    "scant",
    "level",
    "generous",
    "about",
    "approximately",
    "approx",
    "plus",
    "more",
    "additional",
    "desired",
    "several",
    "few",
    "some",
    "any",
    "your",
    "favorite",
    "choice",
    "good",
    "quality",
    "ripe",
    "taste",
    "garnish",
    "serving",
    "needed",
    "flavor",
    "flavored",
    "thin",
    "thick",
    "sweetened",
    "unsweetened",
    "prepared",
    "broken",
    "cut",
    "trimmed",
    "well",
    "plain",
    "regular",
    "very",
    "into",
    "pieces",
    "bite-size",
    "bite-sized",
    "size",
    "sized",
    "inch",
    "in",
}
_EDGE_WORDS = {"of", "or", "and", "for", "to", "the", "with", "a", "an", "&"}

# Names that carry no ingredient on their own.
JUNK_NAMES = {
    "seasoning",
    "seasonings",
    "ingredients",
    "ingredient",
    "garnish",
    "topping",
    "toppings",
    "filling",
    "crust",
    "frosting",
    "glaze",
    "batter",
    "dough",
    "base",
    "icing",
    "liquid",
    "choice",
    "mixture",
    "sauce",
    "optional",
    "other",
    "salt and pepper to",
    "etc",
    "stuff",
    "anything",
}

_TOKEN = re.compile(r"[a-zà-ÿ][a-zà-ÿ'&\-]*|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛]")
_PARENS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_INCHES = re.compile(
    r"\b\d+(?:\s*[-x]\s*\d+)?\s*(?:-|\s)?(?:inch|in\.|\")(?:es)?", re.I
)
_NOTE_SPLIT = re.compile(r"\s+-\s+|;|:|\*")


def _strip_words(words: List[str]) -> List[str]:
    while words and words[0] in _EDGE_WORDS:
        words = words[1:]
    while words and words[-1] in _EDGE_WORDS:
        words = words[:-1]
    return words


def _name_from_chunk(chunk: str) -> Optional[str]:
    words = []
    for token in _TOKEN.findall(chunk):
        token = token.strip("'-")
        if not token or token[0].isdigit() or token in UNICODE_FRACTIONS:
            continue
        if token in UNIT_SET or token in DESCRIPTOR_WORDS:
            continue
        words.append(token)
    words = _strip_words(words)
    if not words:
        return None
    name = " ".join(words)
    if name in JUNK_NAMES or len(words) > 5 or len(name) < 2:
        return None
    return name


@lru_cache(maxsize=200_000)
def name_from_line(line: str) -> Optional[str]:
    """Best-effort ingredient name from a raw line like '1 (8 oz.) pkg. spaghetti, cooked'."""
    text = line.lower().strip()
    if not text or text.endswith(":"):
        return None  # section headers such as "Filling:"
    text = _INCHES.sub(" ", _PARENS.sub(" ", text))
    text = _NOTE_SPLIT.split(text, maxsplit=1)[0]
    for chunk in text.split(","):
        name = _name_from_chunk(chunk)
        if name:
            return name
    return None


_LEADING_CONTAINER = re.compile(
    r"^(?:cloves?|heads?|stalks?|ribs?|sprigs?|bunch(?:es)?|cans?|jars?|pkgs?|"
    r"packages?|boxes?|bags?|sticks?|pinch|dash|slices?|pieces?|squares?)\s+(?:of\s+)?(?=\w)"
)


@lru_cache(maxsize=200_000)
def normalize_name(name: str) -> Optional[str]:
    """Normalise an NER ingredient name: lowercase, drop leading descriptors/containers."""
    text = _squash(_PARENS.sub(" ", name.lower())).strip(" .,;:-*'\"")
    words = text.split()
    while words and (words[0] in DESCRIPTOR_WORDS or words[0] in UNIT_SET):
        words = words[1:]
    words = _strip_words(words)
    text = _LEADING_CONTAINER.sub("", " ".join(words))
    if not text or not re.search(r"[a-z]{2}", text) or text in JUNK_NAMES:
        return None
    if text in DESCRIPTOR_WORDS or text in UNIT_SET:
        return None
    return text


def build_ingredients(
    raw_lines: List[str], ner: List[str]
) -> Tuple[List[str], List[Optional[str]], float]:
    """
    Clean ingredient names (NER first, then raw lines NER missed), their
    quantities, and the share of raw lines that map to a name.
    """
    names: List[str] = []
    seen = set()

    def add(name: Optional[str]) -> None:
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    useful_ner = []
    for item in ner:
        normalized = normalize_name(item)
        if normalized:
            useful_ner.append(item.lower().strip())
            add(normalized)

    lines_lower = [line.lower() for line in raw_lines]
    matched_lines = 0
    for line, lower in zip(raw_lines, lines_lower):
        if any(item and item in lower for item in useful_ner):
            matched_lines += 1
            continue
        fallback = name_from_line(line)
        if fallback:
            matched_lines += 1
            add(fallback)

    quantities: List[Optional[str]] = []
    for name in names:
        source_line = next(
            (raw for raw, low in zip(raw_lines, lines_lower) if name in low), None
        )
        quantities.append(extract_quantity(source_line) if source_line else None)

    coverage = matched_lines / len(raw_lines) if raw_lines else 0.0
    return names, quantities, coverage


# --------------------------------------------------------------------------
# Ingredient categories (for grouping in the UI)
# --------------------------------------------------------------------------

_CATEGORY_RULES: List[Tuple[str, re.Pattern]] = [
    ("nuts_seeds", _phrases_re([r"(?:peanut|almond|cashew|nut) butter", "nutella"])),
    (
        "other",
        _phrases_re(
            [
                r"cream of \w+(?: \w+)? soup",
                r"(?:\w+ )?soup(?: mix)?",
                "broth",
                "stock",
                "bouillon",
                "consomme",
                "cream of tartar",
                "baking (?:soda|powder)",
                "yeast",
                "cornstarch",
                "water",
                "ice",
                "gelatine?",
                r"jell-?o",
                "pudding(?: mix)?",
                "food coloring",
                "cake mix",
            ]
        ),
    ),
    (
        "vegetable",
        _phrases_re(
            [
                r"(?:bell|green|red|yellow|orange|jalapeno|jalapeño|chil[ie]|poblano|banana|sweet) peppers?",
                "butternut squash",
                "eggplants?",
                r"(?:green|string|wax) beans",
                "sweet potato(?:es)?",
                r"green onions?",
                "scallions?",
            ]
        ),
    ),
    (
        "herbs_spices",
        _phrases_re(
            [
                r"(?:garlic|onion|celery|seasoned) (?:salt|powder)",
                "lemon pepper",
                r"(?:black|white|cayenne|red) pepper(?: flakes)?",
                r"pepper$",
                "^pepper",
                "chili powder",
                "curry powder",
                r"bay leaf|bay leaves",
                r"vanilla(?: extract)?",
                r"\w+ extract",
                r"(?:\w+ )?seasoning",
            ]
        ),
    ),
    ("fruit", _phrases_re([r"coconut(?: milk| cream)?", "cream of coconut"])),
    (
        "protein",
        _words_re(
            [
                "chicken",
                "beef",
                "pork",
                "lamb",
                "turkey",
                "duck",
                "veal",
                "venison",
                "ham",
                "bacon",
                "sausage",
                "pepperoni",
                "salami",
                "hamburger",
                "meat",
                "steak",
                "ribs",
                "fish",
                "salmon",
                "tuna",
                "cod",
                "tilapia",
                "shrimp",
                "crab",
                "crabmeat",
                "lobster",
                "clam",
                "oyster",
                "scallop",
                "egg",
                "tofu",
                "tempeh",
                "seitan",
                "bean",
                "lentil",
                "chickpea",
                "garbanzo",
                "chuck",
                "sirloin",
                "brisket",
                "roast",
                "chop",
                "frankfurter",
                "hot dog",
                "wiener",
                "kielbasa",
                "chorizo",
                "anchovy",
                "anchovie",
                "sardine",
            ]
        ),
    ),
    (
        "dairy",
        _phrases_re(
            [
                r"milk",
                r"buttermilk",
                r"(?:sour |heavy |whipping |light |ice |whipped )?cream",
                r"butter",
                r"(?:\w+ )?cheese",
                r"cheddar",
                r"mozzarella",
                r"parmesan",
                r"ricotta",
                r"yogh?urt",
                r"half[- ]and[- ]half",
                r"ghee",
                r"cool whip",
                r"whipped topping",
                r"velveeta",
                r"cheez whiz",
            ]
        ),
    ),
    (
        "oils_fats",
        _words_re(
            [
                "oil",
                "margarine",
                "shortening",
                "lard",
                "crisco",
                "oleo",
                "cooking spray",
            ]
        ),
    ),
    (
        "sweetener",
        _words_re(
            [
                "sugar",
                "honey",
                "syrup",
                "molasses",
                "maple",
                "stevia",
                "splenda",
                "sweetener",
                "agave",
                "chocolate",
                "cocoa",
                "marshmallow",
                "candy",
                "caramel",
                "chips",
            ]
        ),
    ),
    (
        "grain",
        _words_re(
            [
                "flour",
                "rice",
                "pasta",
                "spaghetti",
                "macaroni",
                "noodle",
                "bread",
                "breadcrumb",
                "crumb",
                "oat",
                "oatmeal",
                "cereal",
                "cracker",
                "tortilla",
                "cornmeal",
                "couscous",
                "quinoa",
                "barley",
                "bulgur",
                "bisquick",
                "biscuit",
                "roll",
                "bun",
                "pie crust",
                "pie shell",
                "wheat",
                "lasagna",
                "grits",
                "pretzel",
                "graham",
            ]
        ),
    ),
    (
        "nuts_seeds",
        _words_re(
            [
                "almond",
                "walnut",
                "pecan",
                "cashew",
                "peanut",
                "hazelnut",
                "pistachio",
                "macadamia",
                "pine nut",
                "nut",
                "nutmeat",
                "seed",
                "sesame",
                "chia",
                "flax",
            ]
        ),
    ),
    (
        "herbs_spices",
        _words_re(
            [
                "salt",
                "pepper",
                "basil",
                "oregano",
                "thyme",
                "rosemary",
                "parsley",
                "cilantro",
                "dill",
                "dill weed",
                "sage",
                "mint",
                "cumin",
                "paprika",
                "cinnamon",
                "nutmeg",
                "ginger",
                "clove",
                "allspice",
                "cayenne",
                "turmeric",
                "chives",
                "tarragon",
                "marjoram",
                "coriander",
                "spice",
                "herb",
            ]
        ),
    ),
    (
        "vegetable",
        _words_re(
            [
                "onion",
                "garlic",
                "tomato",
                "tomatoe",
                "carrot",
                "celery",
                "potato",
                "potatoe",
                "broccoli",
                "cauliflower",
                "spinach",
                "lettuce",
                "zucchini",
                "cucumber",
                "mushroom",
                "cabbage",
                "kale",
                "squash",
                "corn",
                "pea",
                "asparagus",
                "beet",
                "radish",
                "leek",
                "shallot",
                "pumpkin",
                "olive",
                "artichoke",
                "avocado",
                "sauerkraut",
                "chile",
                "chili",
                "greens",
                "vegetable",
                "pimiento",
                "pimento",
                "okra",
                "turnip",
                "parsnip",
            ]
        ),
    ),
    (
        "fruit",
        _words_re(
            [
                "apple",
                "banana",
                "orange",
                "lemon",
                "lime",
                "grape",
                "berry",
                "berrie",
                "strawberry",
                "strawberrie",
                "blueberry",
                "blueberrie",
                "raspberry",
                "raspberrie",
                "cranberry",
                "cranberrie",
                "cherry",
                "cherrie",
                "peach",
                "peache",
                "pear",
                "pineapple",
                "mango",
                "raisin",
                "date",
                "fig",
                "apricot",
                "plum",
                "melon",
                "kiwi",
                "rhubarb",
                "fruit",
                "juice",
                "zest",
                "peel",
            ]
        ),
    ),
    (
        "condiment",
        _words_re(
            [
                "ketchup",
                "catsup",
                "mustard",
                "mayonnaise",
                "mayo",
                "vinegar",
                "sauce",
                "dressing",
                "salsa",
                "relish",
                "worcestershire",
                "tabasco",
                "jam",
                "jelly",
                "preserves",
                "marmalade",
                "pickle",
                "horseradish",
                "wine",
                "sherry",
            ]
        ),
    ),
]


@lru_cache(maxsize=200_000)
def categorize_ingredient(name: str) -> str:
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(name):
            return category
    return "other"


# --------------------------------------------------------------------------
# Dietary and nutrition labels
# --------------------------------------------------------------------------

MEAT_RE = _words_re(
    [
        "chicken",
        "beef",
        "pork",
        "lamb",
        "mutton",
        "turkey",
        "duck",
        "goose",
        "veal",
        "venison",
        "bison",
        "rabbit",
        "ham",
        "bacon",
        "sausage",
        "pepperoni",
        "salami",
        "prosciutto",
        "pancetta",
        "chorizo",
        "bologna",
        "hot dog",
        "frankfurter",
        "wiener",
        "kielbasa",
        "bratwurst",
        "hamburger",
        "meat",
        "meatball",
        "steak",
        "rib",
        "sparerib",
        "brisket",
        "chuck",
        "sirloin",
        "tenderloin",
        "pot roast",
        "rump roast",
        "jerky",
        "liver",
        "giblet",
        "gizzard",
        "oxtail",
        "tripe",
        "lard",
        "suet",
        "gelatin",
        "gelatine",
        "jello",
        "jell-o",
        "spam",
        "pastrami",
        "drumstick",
        "thigh",
        "wing",
        "bone",
        "fish",
        "salmon",
        "tuna",
        "cod",
        "tilapia",
        "halibut",
        "trout",
        "catfish",
        "haddock",
        "snapper",
        "mahi",
        "sardine",
        "anchovy",
        "anchovie",
        "herring",
        "mackerel",
        "shrimp",
        "prawn",
        "crab",
        "crabmeat",
        "lobster",
        "clam",
        "oyster",
        "scallop",
        "mussel",
        "squid",
        "calamari",
        "octopus",
        "crawfish",
        "crayfish",
        "seafood",
        "poultry",
        "pheasant",
        "quail",
        "cornish hen",
        "hen",
        "roaster",
        "fryer",
        "broiler",
        "chop",
        "loin",
        "shank",
        "flank",
        "roast beef",
        "corned beef",
        "ground round",
        "round steak",
        "bass",
        "perch",
        "pike",
        "walleye",
        "flounder",
        "sole",
        "grouper",
        "swordfish",
        "whitefish",
        "pollock",
        "roughy",
        "orange roughy",
        "caviar",
        "roe",
        "lox",
        "bacon bit",
    ]
)
MEAT_EXCEPTIONS = _phrases_re(
    [
        r"(?:hamburger|hot dog) buns?",
        r"nut ?meats?",
        r"crab ?apples?",
        "duck sauce",
        r"beefsteak tomato(?:es)?",
        "meatless",
        r"(?:vegetarian|veggie|vegan|meatless|soy|plant[- ]based) \w+",
        r"imitation bacon bits",
        r"chocolate chips?",
        r"(?:pork|beef) rinds?",
        r"chicken[- ]flavor(?:ed)? \w+",
        r"bone[- ]dry",
        r"jelly roll",
        "fryer oil",
        r"wing ?nuts?",
    ]
)
# Meat that only flavours a dish (doesn't make it high-protein).
MINOR_MEAT = _phrases_re(
    [
        r"(?:chicken|beef|turkey|ham|vegetable) (?:broth|stock|bouillon|base|soup|gravy)",
        r"bouillon(?: cubes?)?",
        r"bacon (?:grease|drippings|fat|bits)",
        "lard",
        "suet",
        r"gelatine?",
        r"jell-?o",
        "jello",
        r"(?:soup )?bones?",
        r"fish sauce",
        r"anchov(?:y|ies) paste",
    ]
)

DAIRY_RE = _phrases_re(
    [
        r"milks?",
        "buttermilk",
        r"creams?",
        "butter",
        r"cheeses?",
        "cheddar",
        "mozzarella",
        "parmesan",
        "ricotta",
        "provolone",
        "gouda",
        "brie",
        "feta",
        "velveeta",
        "cheez whiz",
        r"yogh?urts?",
        "ghee",
        "whey",
        "casein",
        r"half[- ]and[- ]half",
        "cool whip",
        "whipped topping",
        "oleo",
    ]
)
DAIRY_EXCEPTIONS = _phrases_re(
    [
        r"(?:peanut|almond|cashew|nut|apple|cocoa|shea|sunflower|seed|soy|vegan|plant) butter",
        r"(?:coconut|almond|soy|rice|oat|cashew|hemp|vegan|plant|non-?dairy) (?:milk|cream|cheese|yogh?urt|creamer)s?",
        "soymilk",
        "cream of coconut",
        "cream of tartar",
        r"butter (?:beans?|lettuce|flavor(?:ing)?|extract)",
        r"cream[- ]style",
        "creamed corn",
        r"non-?dairy",
        r"dairy[- ]free",
        r"ice cream salt",
        r"milk of magnesia",
        r"coconut cream",
    ]
)
EGG_RE = _words_re(
    ["egg", "egg white", "egg yolk", "mayonnaise", "mayo", "meringue", "eggnog"]
)
EGG_EXCEPTIONS = _phrases_re(
    [
        r"egg replacer",
        r"vegan egg(?: substitute)?",
        r"flax ?egg",
        r"vegan mayo(?:nnaise)?",
    ]
)
HONEY_RE = _words_re(["honey"], plural=False)

GLUTEN_RE = _words_re(
    [
        "flour",
        "wheat",
        "bread",
        "breadcrumb",
        "bread crumb",
        "crumb",
        "pasta",
        "spaghetti",
        "macaroni",
        "noodle",
        "lasagna",
        "lasagne",
        "fettuccine",
        "linguine",
        "penne",
        "rigatoni",
        "ziti",
        "orzo",
        "couscous",
        "bulgur",
        "barley",
        "rye",
        "semolina",
        "farina",
        "spelt",
        "seitan",
        "malt",
        "beer",
        "ale",
        "lager",
        "cracker",
        "saltine",
        "ritz",
        "graham",
        "pretzel",
        "cookie",
        "cake",
        "pie crust",
        "pie shell",
        "pastry",
        "phyllo",
        "filo",
        "dough",
        "biscuit",
        "bisquick",
        "pancake mix",
        "tortilla",
        "pita",
        "bun",
        "roll",
        "crouton",
        "stuffing",
        "panko",
        "soy sauce",
        "teriyaki",
        "brownie",
        "muffin",
        "waffle",
        "wafer",
        "matzo",
        "matzoh",
        "cereal",
        "cheerios",
        "wheaties",
        "stove top",
        "gravy mix",
        "cream of mushroom soup",
        "cream of chicken soup",
        "cream of celery soup",
        "dumpling",
        "wonton",
        "egg roll wrapper",
        "bagel",
        "croissant",
        "english muffin",
        "pizza crust",
    ]
)
GLUTEN_EXCEPTIONS = _phrases_re(
    [
        r"(?:rice|almond|coconut|corn|potato|tapioca|chickpea|garbanzo|buckwheat|oat|sorghum|millet|cassava|arrowroot|soy|gluten[- ]free) flours?",
        "cornflour",
        r"masa(?: harina)?",
        r"rice (?:noodles?|sticks?|paper|crackers?|cakes?)",
        r"corn tortillas?",
        r"gluten[- ]free \w+(?: \w+)?",
        r"tamari",
        r"rice cereal",
        r"(?:fish|crab|potato|salmon|rice) cakes?",
        r"cake (?:pan|tin)s?",
        r"egg rolls? wrappers? free",
        r"roll(?:ed)? oats",
        r"jelly roll pan",
    ]
)

NUT_RE = _words_re(
    [
        "almond",
        "walnut",
        "pecan",
        "cashew",
        "peanut",
        "hazelnut",
        "filbert",
        "pistachio",
        "macadamia",
        "brazil nut",
        "pine nut",
        "pignoli",
        "chestnut",
        "nut",
        "nutmeat",
        "nut meat",
        "praline",
        "marzipan",
        "almond paste",
        "nutella",
        "mixed nut",
    ]
)
NUT_EXCEPTIONS = _phrases_re(
    [r"water chestnuts?", r"nut[- ]free", r"(?:almond|nut) extract free"]
)

HIGH_CARB_RE = _words_re(
    [
        "sugar",
        "flour",
        "bread",
        "pasta",
        "spaghetti",
        "macaroni",
        "noodle",
        "rice",
        "potato",
        "potatoe",
        "corn",
        "cornmeal",
        "oat",
        "oatmeal",
        "bean",
        "lentil",
        "chickpea",
        "quinoa",
        "honey",
        "syrup",
        "molasses",
        "banana",
        "raisin",
        "date",
        "cake mix",
        "tortilla",
        "cracker",
        "cereal",
        "couscous",
        "barley",
        "jam",
        "jelly",
        "preserves",
        "marshmallow",
        "chocolate chip",
        "pudding",
        "jello",
        "jell-o",
        "condensed milk",
        "biscuit",
        "bisquick",
        "bun",
        "roll",
        "pie crust",
        "pie shell",
        "graham",
        "cookie",
        "candy",
        "caramel",
        "dough",
        "pancake mix",
    ]
)
HIGH_CARB_EXCEPTIONS = _phrases_re(
    [
        r"(?:sugar|carb)[- ]free \w+",
        r"sugar (?:substitute|replacement)",
        r"no sugar",
        r"rice (?:vinegar|wine)",
        r"(?:green|string|wax|french[- ]cut) beans",
        r"corn ?(?:oil|starch)",
        r"pepper ?corns?",
        r"(?:almond|coconut) flour",
        r"egg roll",
        r"rolled? up",
    ]
)

PLANT_PROTEIN_RE = _words_re(
    [
        "tofu",
        "tempeh",
        "seitan",
        "lentil",
        "chickpea",
        "garbanzo",
        "black bean",
        "kidney bean",
        "pinto bean",
        "navy bean",
        "white bean",
        "cannellini",
        "great northern bean",
        "lima bean",
        "edamame",
        "split pea",
        "refried bean",
        "protein powder",
    ]
)
SMALL_PROTEIN_RE = _words_re(
    ["egg", "cheese", "cottage cheese", "greek yogurt", "quinoa"]
)

LOW_FAT_HINT_RE = _phrases_re(
    [
        r"fat[- ]free",
        r"low[- ]fat",
        r"non[- ]?fat",
        r"reduced[- ]fat",
        "lean",
        "skim",
        "skinless",
        "light",
        "lite",
        r"(?:nonstick|cooking|vegetable) spray",
        "egg whites?",
    ]
)
LOWFAT_QUALIFIED = re.compile(
    r"\b(?:fat[- ]free|low[- ]fat|non[- ]?fat|reduced[- ]fat|light|lite|skim|part[- ]skim|lean)\s+[\w-]+(?:\s+[\w-]+)?"
)
HIGH_FAT_RE = _words_re(
    [
        "butter",
        "margarine",
        "oleo",
        "shortening",
        "lard",
        "crisco",
        "cream",
        "cheese",
        "bacon",
        "sausage",
        "mayonnaise",
        "mayo",
        "salami",
        "pepperoni",
        "cream cheese",
        "sour cream",
        "whipping cream",
        "heavy cream",
        "ice cream",
        "coconut milk",
    ]
)
DEEP_FRY_RE = _phrases_re(
    [
        r"deep[- ]?(?:fat )?fr(?:y|ied)",
        r"fry in (?:hot )?(?:oil|fat|lard|shortening)",
        "fried",
    ]
)

FIBER_RE = _words_re(
    [
        "bean",
        "lentil",
        "chickpea",
        "garbanzo",
        "split pea",
        "pea",
        "whole wheat",
        "whole grain",
        "bran",
        "oat",
        "oatmeal",
        "rolled oat",
        "barley",
        "brown rice",
        "quinoa",
        "bulgur",
        "chia",
        "flax",
        "flaxseed",
        "broccoli",
        "brussels sprout",
        "artichoke",
        "avocado",
        "raspberry",
        "raspberrie",
        "blackberry",
        "blackberrie",
        "prune",
        "fig",
        "sweet potato",
        "kale",
        "collard",
        "lentil",
        "edamame",
    ]
)


def _has(
    pattern: re.Pattern, text: str, exceptions: Optional[re.Pattern] = None
) -> bool:
    if exceptions is not None:
        text = exceptions.sub(" ", text)
    return bool(pattern.search(text))


def classify_diet(
    ingredient_text: str, directions_text: str, is_dessert: bool
) -> Dict[str, bool]:
    """Dietary and nutrition flags from clean names + raw lines (``ingredient_text``)."""
    text = ingredient_text
    has_meat = _has(MEAT_RE, text, MEAT_EXCEPTIONS)
    has_main_meat = _has(MEAT_RE, MINOR_MEAT.sub(" ", MEAT_EXCEPTIONS.sub(" ", text)))
    has_dairy = _has(DAIRY_RE, text, DAIRY_EXCEPTIONS)
    has_egg = _has(EGG_RE, text, EGG_EXCEPTIONS)
    has_gluten = _has(GLUTEN_RE, text, GLUTEN_EXCEPTIONS)
    has_nuts = _has(NUT_RE, text, NUT_EXCEPTIONS)
    has_carbs = _has(HIGH_CARB_RE, text, HIGH_CARB_EXCEPTIONS)

    small_protein = {m.group(0) for m in SMALL_PROTEIN_RE.finditer(text)}
    high_protein = not is_dessert and (
        has_main_meat or _has(PLANT_PROTEIN_RE, text) or len(small_protein) >= 2
    )

    fat_check_text = LOWFAT_QUALIFIED.sub(" ", text)
    low_fat = (
        _has(LOW_FAT_HINT_RE, text)
        and not _has(HIGH_FAT_RE, fat_check_text, DAIRY_EXCEPTIONS)
        and not _has(DEEP_FRY_RE, directions_text)
    )
    fiber_sources = {m.group(0) for m in FIBER_RE.finditer(text)}

    return {
        "is_vegetarian": not has_meat,
        "is_vegan": not (has_meat or has_dairy or has_egg or _has(HONEY_RE, text)),
        "is_gluten_free": not has_gluten,
        "is_dairy_free": not has_dairy,
        "is_nut_free": not has_nuts,
        "is_low_carb": not has_carbs and not is_dessert,
        "is_high_protein": high_protein,
        "is_low_fat": low_fat,
        "is_high_fiber": len(fiber_sources) >= 2,
    }


# --------------------------------------------------------------------------
# Meal type (from the title, falling back to ingredients)
# --------------------------------------------------------------------------

MEAL_RULES: List[Tuple[str, re.Pattern]] = [
    (
        "drink",
        _phrases_re(
            [
                r"punch",
                r"lemonade",
                r"limeade",
                r"smoothies?",
                r"(?:milk ?)?shakes?",
                r"iced tea",
                r"sweet tea",
                r"spiced tea",
                r"tea$",
                r"cocktails?",
                r"margaritas?",
                r"sangria",
                r"egg ?nog",
                r"(?:hot |mulled |apple |spiced )cider",
                r"mulled wine",
                r"martinis?",
                r"daiquiris?",
                r"juleps?",
                r"toddy",
                r"frappes?",
                r"lattes?",
                r"lassi",
                r"slush(?:ies|y)?",
                r"spritzers?",
                r"beverages?",
                r"drinks?",
                r"(?:hot )?cocoa$",
                r"hot chocolate",
                r"coffee$",
                r"wassail",
                r"cordial",
                r"liqueur",
                r"sodas?$",
                r"floats?$",
                r"coolers?$",
                r"fizz",
                r"flip$",
                r"breeze$",
                r"mojitos?",
                r"mimosas?",
                r"bloody mary",
                r"highball",
                r"sours?$",
                r"nectar$",
                r"tonic$",
                r"elixir",
                r"champagne",
            ]
        ),
    ),
    (
        "breakfast",
        _phrases_re(
            [
                r"pancakes?",
                r"hot ?cakes?",
                r"griddle ?cakes?",
                r"johnny ?cakes?",
                r"waffles?",
                r"french toast",
                r"omelets?",
                r"omelettes?",
                r"frittatas?",
                r"quiches?",
                r"granola",
                r"oatmeal",
                r"porridge",
                r"muffins?",
                r"scones?",
                r"breakfast",
                r"brunch",
                r"coffee ?cakes?",
                r"crepes?",
                r"biscuits and gravy",
                r"sausage gravy",
                r"hash ?browns?",
                r"eggs? benedict",
                r"scrambled eggs?",
                r"egg casserole",
                r"cinnamon (?:rolls?|buns?)",
                r"sticky buns?",
                r"doughnuts?",
                r"donuts?",
                r"danish(?:es)?",
                r"bagels?",
                r"grits",
                r"monkey bread",
                r"blintz(?:es)?",
                r"popovers?",
            ]
        ),
    ),
    (
        "dessert",
        _phrases_re(
            [
                r"cakes?",
                r"cupcakes?",
                r"cheesecakes?",
                r"cookies?",
                r"brownies?",
                r"fudge",
                r"cand(?:y|ies)",
                r"brittle",
                r"toffee",
                r"truffles?",
                r"bon ?bons?",
                r"puddings?",
                r"tarts?",
                r"tortes?",
                r"cobblers?",
                r"crisp",
                r"crumble",
                r"desserts?",
                r"sundaes?",
                r"ice cream",
                r"sherbets?",
                r"sorbets?",
                r"gelato",
                r"mousse",
                r"custards?",
                r"flan",
                r"meringues?",
                r"macaroons?",
                r"frostings?",
                r"icings?",
                r"eclairs?",
                r"cream puffs?",
                r"baklava",
                r"strudel",
                r"trifle",
                r"parfaits?",
                r"shortcakes?",
                r"bars",
                r"squares",
                r"divinity",
                r"pralines?",
                r"bark",
                r"caramels?",
                r"marshmallows?",
                r"snowballs?",
                r"pies?",
                r"delight",
                r"dumplings?",
                r"bread pudding",
                r"cheese ?cake",
                r"kisses",
                r"turnovers?",
                r"blondies?",
                r"snickerdoodles?",
                r"biscotti",
                r"gingerbread",
                r"fluff",
                r"dream",
                r"heaven",
                r"sweets?",
                r"confections?",
                r"glaze",
                r"crunch",
                r"financiers?",
                r"clafoutis",
                r"tiramisu",
                r"panna cotta",
                r"zabaglione",
            ]
        ),
    ),
    (
        "snack",
        _phrases_re(
            [
                r"dips?",
                r"salsa",
                r"guacamole",
                r"hummus",
                r"appetizers?",
                r"hors d'?oeuvres?",
                r"snacks?",
                r"party mix",
                r"chex mix",
                r"trail mix",
                r"snack mix",
                r"popcorn",
                r"nachos?",
                r"deviled eggs?",
                r"cheese ?balls?",
                r"spreads?",
                r"pinwheels?",
                r"bruschetta",
                r"crostini",
                r"stuffed mushrooms?",
                r"(?:buffalo |chicken )wings?",
                r"roll[- ]ups?",
                r"puppy chow",
                r"munch(?:ies)?",
                r"jerky",
                r"(?:spiced|sugared|candied|roasted) (?:nuts|pecans|almonds|walnuts)",
                r"crackers?",
                r"chips",
                r"pretzels?",
                r"canapes?",
                r"finger foods?",
                r"poppers?",
                r"egg rolls?",
                r"spring rolls?",
                r"wontons?",
                r"quesadillas?",
                r"cheese straws?",
                r"pate",
                r"terrine",
                r"mezze",
            ]
        ),
    ),
]
_SAVORY_PIE = _phrases_re(
    [
        "pot pie",
        "shepherd",
        "tamale pie",
        "pizza",
        "cottage pie",
        "meat pie",
        r"(?:chicken|beef|pork|turkey|ham|sausage|hamburger|taco|tuna|salmon|spinach|onion|tomato|vegetable|cheese|egg|crab|seafood|zucchini|mushroom) pies?",
        "pork pie",
        r"(?:crab|fish|salmon|tuna|potato|rice|corn|zucchini|shrimp) cakes?",
        r"corn pudding",
        r"yorkshire pudding",
        r"(?:chicken|beef|pork) (?:and|&|n') dumplings?",
        r"tomato tart",
        r"onion tart",
        r"cheese ?balls?",
    ]
)
SIDE_CONDIMENT = _phrases_re(
    [
        r"sauces?",
        r"gravy",
        r"dressings?",
        r"marinades?",
        r"rubs?",
        r"seasonings?",
        r"jams?",
        r"jell(?:y|ies)",
        r"preserves",
        r"marmalades?",
        r"relish(?:es)?",
        r"chutneys?",
        r"pickles?",
        r"pickled",
        r"stuffing",
        r"butters?$",
        r"syrups?",
        r"mustard",
        r"ketchup",
        r"catsup",
        r"vinaigrette",
        r"aioli",
        r"pesto",
        r"mayonnaise",
        r"spice mix",
        r"conserve",
        r"curd",
        r"compote",
        r"chow ?chow",
    ]
)
LUNCH_RULE = _phrases_re(
    [
        r"sandwich(?:es)?",
        r"burgers?",
        r"wraps?",
        r"soups?",
        r"chowders?",
        r"bisques?",
        r"salads?",
        r"subs?",
        r"hoagies?",
        r"paninis?",
        r"sloppy joes?",
        r"pitas?",
        r"gyros?",
        r"grilled cheese",
        r"hot dogs?",
        r"po'? ?boys?",
        r"melts?",
        r"heroes",
        r"gazpacho",
        r"minestrone",
        r"lunch",
        r"slaw",
        r"coleslaw",
        r"stew$",
    ]
)
DINNER_RULE = _phrases_re(
    [
        r"chicken",
        r"beef",
        r"pork",
        r"steaks?",
        r"ham",
        r"turkey",
        r"lamb",
        r"veal",
        r"venison",
        r"fish",
        r"salmon",
        r"tuna",
        r"shrimp",
        r"crab",
        r"lobster",
        r"scallops?",
        r"meat ?loaf",
        r"meat ?balls?",
        r"sausages?",
        r"chops",
        r"ribs",
        r"roast",
        r"brisket",
        r"casseroles?",
        r"lasagna",
        r"lasagne",
        r"spaghetti",
        r"pasta",
        r"noodles",
        r"stews?",
        r"chili",
        r"curry",
        r"stir[- ]?fry",
        r"enchiladas?",
        r"tacos?",
        r"burritos?",
        r"pot pie",
        r"pizzas?",
        r"risotto",
        r"paella",
        r"jambalaya",
        r"gumbo",
        r"stroganoff",
        r"parmesan",
        r"parmigiana",
        r"alfredo",
        r"goulash",
        r"hot ?dish",
        r"main dish",
        r"entree",
        r"dinner",
        r"supper",
        r"fajitas?",
        r"kabobs?",
        r"kebabs?",
        r"skillet",
        r"bake$",
        r"manicotti",
        r"ravioli",
        r"tortellini",
        r"shells",
        r"cacciatore",
        r"fricassee",
        r"pot roast",
        r"meat",
        r"ziti",
        r"macaroni",
        r"quiche",
        r"fillets?",
        r"loin",
        r"tenderloin",
        r"hash",
        r"chow mein",
        r"lo mein",
        r"fried rice",
        r"tamales?",
        r"cabbage rolls",
        r"stuffed peppers",
    ]
)
SIDE_RULE = _phrases_re(
    [
        r"breads?",
        r"rolls",
        r"biscuits?",
        r"corn ?bread",
        r"buns",
        r"loaf",
        r"potatoes",
        r"potato",
        r"rice",
        r"beans",
        r"vegetables?",
        r"veggies",
        r"carrots",
        r"corn",
        r"peas",
        r"squash",
        r"broccoli",
        r"cauliflower",
        r"asparagus",
        r"spinach",
        r"cabbage",
        r"pilaf",
        r"fries",
        r"au gratin",
        r"scalloped",
        r"mashed",
        r"side dish",
        r"greens",
        r"zucchini",
        r"eggplant",
        r"mushrooms",
        r"onions",
        r"tomatoes",
        r"yams",
        r"slaw",
        r"stuffing",
        r"dressing",
        r"succotash",
        r"hush ?puppies",
        r"dumplings",
        r"sauerkraut",
        r"applesauce",
        r"fritters?",
        r"souffle",
        r"medley",
        r"focaccia",
        r"tortillas",
    ]
)

ALCOHOL_RE = _words_re(
    [
        "rum",
        "vodka",
        "gin",
        "tequila",
        "whiskey",
        "whisky",
        "bourbon",
        "brandy",
        "liqueur",
        "schnapps",
        "champagne",
        "triple sec",
        "vermouth",
        "kahlua",
        "grand marnier",
        "amaretto",
        "cognac",
    ]
)
DRINK_BASE_RE = _words_re(
    [
        "juice",
        "soda",
        "ginger ale",
        "club soda",
        "tonic",
        "lemonade",
        "ice",
        "ice cube",
        "sprite",
        "7-up",
        "cola",
        "seltzer",
        "sparkling water",
    ]
)
SOLID_FOOD_RE = _words_re(
    ["flour", "meat", "chicken", "beef", "rice", "pasta", "bread", "potato"]
)

DESSERT_INGREDIENTS = _words_re(
    [
        "sugar",
        "brown sugar",
        "powdered sugar",
        "confectioners sugar",
        "chocolate",
        "chocolate chip",
        "cocoa",
        "vanilla",
        "cool whip",
        "whipped topping",
        "marshmallow",
        "frosting",
        "condensed milk",
        "pudding",
        "cake mix",
        "jello",
        "jell-o",
        "corn syrup",
        "graham cracker",
        "pie filling",
        "coconut",
        "butterscotch",
        "caramel",
        "sprinkles",
        "maraschino cherrie",
    ]
)
SAVORY_INGREDIENTS = _words_re(
    [
        "onion",
        "garlic",
        "black pepper",
        "chicken",
        "beef",
        "pork",
        "ham",
        "bacon",
        "sausage",
        "fish",
        "shrimp",
        "celery",
        "tomato",
        "tomatoe",
        "mustard",
        "soy sauce",
        "worcestershire",
        "broth",
        "bouillon",
        "cheddar",
        "parmesan",
    ]
)


def classify_meal_type(title: str, ingredient_text: str, has_meat: bool) -> str:
    t = title.lower()
    savory_title = bool(_SAVORY_PIE.search(t))
    for meal, pattern in MEAL_RULES:
        if meal == "dessert" and savory_title:
            continue
        if (
            meal == "snack"
            and SIDE_CONDIMENT.search(t)
            and not re.search(r"dips?|salsa|spreads?", t)
        ):
            continue
        if pattern.search(t):
            return meal
    if SIDE_CONDIMENT.search(t):
        return "side"
    if LUNCH_RULE.search(t):
        return "lunch"
    if DINNER_RULE.search(t) or savory_title:
        return "dinner"
    if SIDE_RULE.search(t):
        return "side"

    if (
        ALCOHOL_RE.search(ingredient_text)
        and DRINK_BASE_RE.search(ingredient_text)
        and not SOLID_FOOD_RE.search(ingredient_text)
    ):
        return "drink"
    sweet = len({m.group(0) for m in DESSERT_INGREDIENTS.finditer(ingredient_text)})
    if sweet >= 2 and not SAVORY_INGREDIENTS.search(ingredient_text):
        return "dessert"
    if has_meat:
        return "dinner"
    return "other"


# --------------------------------------------------------------------------
# Times, servings, difficulty
# --------------------------------------------------------------------------

DURATION = re.compile(
    rf"(?P<skip>\b(?:every|each|last|first|intervals? of)\s+(?:\w+\s+)?)?"
    rf"\b(?P<a>{_NUM_ANY})(?:\s*(?:to|-|–|or)\s*(?P<b>{_NUM_ANY}))?\s*"
    rf"(?P<unit>minutes?|mins?|hours?|hrs?|hr)\b\.?"
    rf"(?P<per>\s+(?:per|a|each|for each)\s+(?:pound|lb|inch|side))?",
    re.IGNORECASE,
)
OVERNIGHT = re.compile(r"\bovernight\b", re.IGNORECASE)
EXPLICIT_PREP = re.compile(
    rf"\bprep(?:aration)?(?: time)?\s*:?\s*(?P<a>{_NUM_DIGITS})\s*(?P<unit>minutes?|mins?|hours?|hrs?|hr)\b",
    re.IGNORECASE,
)
HEAT_WORDS = re.compile(
    r"\b(?:bake[sd]?|baking|roast(?:ed|ing)?|cook(?:ed|ing|s)?|boil(?:ed|ing|s)?|simmer(?:ed|ing|s)?|"
    r"fr(?:y|ied|ying)|saut[eé](?:ed|ing)?|broil(?:ed|ing)?|grill(?:ed|ing)?|microwave[ds]?|"
    r"steam(?:ed|ing)?|heat(?:ed|ing)?|brown(?:ed|ing)?|poach(?:ed|ing)?|braise[ds]?|toast(?:ed|ing)?|"
    r"sear(?:ed|ing)?|stew(?:ed|ing)?|barbecue[ds]?|smoke[ds]?|crock ?pot|slow cooker|oven|"
    r"pressure cook|deep[- ]?fry|scald(?:ed|ing)?|melt(?:ed|ing)?|reduce|caramelize)\b",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")
MAX_SINGLE_MINUTES = 48 * 60
MAX_TOTAL_MINUTES = 4 * 24 * 60


def _minutes(match: re.Match) -> Optional[float]:
    a = to_number(match.group("a"))
    b = to_number(match.group("b")) if match.group("b") else None
    value = max(v for v in (a, b) if v is not None) if (a or b) else None
    if value is None or value <= 0:
        return None
    if match.group("unit").lower().startswith("h"):
        value *= 60
    return value if value <= MAX_SINGLE_MINUTES else None


def extract_times(
    steps: List[str], ingredient_count: int = 0
) -> Dict[str, Optional[int]]:
    """
    Prep / cook / total minutes from durations written in the directions.

    Directions rarely state hands-on time ("cook 1 minute" isn't a 1-minute
    recipe), so unless a prep time is stated, prep is at least an estimate of
    5 minutes plus 1 per ingredient (capped at 30).
    """
    prep = cook = passive = 0.0
    found = False
    for step in steps:
        for sentence in SENTENCE_SPLIT.split(step):
            minutes = 0.0
            for match in DURATION.finditer(sentence):
                if match.group("skip") or match.group("per"):
                    continue
                value = _minutes(match)
                if value:
                    minutes += value
            if OVERNIGHT.search(sentence):
                passive += 8 * 60
                found = True
            if not minutes:
                continue
            found = True
            if HEAT_WORDS.search(sentence):
                cook += minutes
            elif re.search(
                r"\b(?:chill|refrigerat|freez|marinat|rest|stand|cool|set|soak|rise|sit|steep|ferment)",
                sentence,
                re.I,
            ):
                passive += minutes
            else:
                prep += minutes

    explicit = None
    for step in steps:
        m = EXPLICIT_PREP.search(step)
        if m:
            explicit = to_number(m.group("a"))
            if explicit and m.group("unit").lower().startswith("h"):
                explicit *= 60
            break
    if explicit:
        prep = explicit
        found = True
    elif found and ingredient_count:
        prep = max(prep, min(30, 5 + ingredient_count))

    total = prep + cook + passive
    if not found or total <= 0 or total > MAX_TOTAL_MINUTES:
        return {"prep_time": None, "cook_time": None, "total_time": None}
    return {
        "prep_time": round(prep) or None,
        "cook_time": round(cook) or None,
        "total_time": max(1, round(total)),
    }


_SERV_NUM = r"(\d{1,3})(?:\s*(?:to|-|–|or)\s*(\d{1,3}))?"
SERVINGS_PATTERNS = [
    re.compile(
        rf"\b(?:serves|serving size|feeds)\s*:?\s*(?:about|approx\.?|approximately|up to)?\s*{_SERV_NUM}",
        re.I,
    ),
    re.compile(rf"\b{_SERV_NUM}\s*(?:servings?|portions?|people|persons)\b", re.I),
    re.compile(
        rf"\b(?:makes|yields?)\s*:?\s*(?:about|approx\.?|approximately)?\s*{_SERV_NUM}\s*(?=[.,;)]|$)",
        re.I,
    ),
]


def extract_servings(title: str, steps: List[str]) -> Optional[int]:
    for text in [title] + steps:
        for pattern in SERVINGS_PATTERNS:
            m = pattern.search(text)
            if m:
                low = int(m.group(1))
                high = int(m.group(2)) if m.group(2) else low
                value = round((low + high) / 2) if high >= low else low
                if 1 <= value <= 100:
                    return value
    return None


TECHNIQUE_RE = re.compile(
    r"\b(?:knead|yeast|candy thermometer|soft[- ]ball|hard[- ]ball|thread stage|deep[- ]?fry|"
    r"deep[- ]fat|temper|souffl|roll (?:out|dough)|phyllo|filo|puff pastry|pastry bag|pipe|"
    r"double boiler|debone|julienne|flamb|proof|punch down|let rise|caramelize|water bath)",
    re.IGNORECASE,
)


def classify_difficulty(
    steps: List[str],
    ingredient_count: int,
    active_minutes: Optional[int],
    all_text: str,
) -> str:
    sentences = sum(
        len([s for s in SENTENCE_SPLIT.split(step) if s.strip()]) for step in steps
    )
    score = 0
    score += 0 if sentences <= 5 else 1 if sentences <= 12 else 2
    score += 0 if ingredient_count <= 7 else 1 if ingredient_count <= 13 else 2
    if active_minutes:
        score += 0 if active_minutes <= 45 else 1 if active_minutes <= 120 else 2
    score += min(2, len({m.group(0).lower() for m in TECHNIQUE_RE.finditer(all_text)}))
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


# --------------------------------------------------------------------------
# Titles and quality
# --------------------------------------------------------------------------

_YIELD_PARENS = re.compile(
    r"\s*\([^)]*\b(?:serv|yield|makes|portion|people)[^)]*\)", re.I
)
_BAD_APOSTROPHE = re.compile(r"(\w)'S\b")
JUNK_TITLE = re.compile(
    r"^(?:helpful |household |kitchen |cooking )?(?:hints?|tips?)\b", re.I
)


def clean_title(title: Any) -> str:
    text = "" if title is None else str(title)
    if text.lower() == "nan":
        text = ""
    text = _YIELD_PARENS.sub(" ", text)
    text = re.sub(r"(\w)\(", r"\1 (", text)
    text = _BAD_APOSTROPHE.sub(r"\1's", text)
    return _squash(text)


def quality_score(
    title: str,
    steps: List[str],
    ingredient_count: int,
    coverage: float,
    has_time: bool,
    has_servings: bool,
) -> float:
    """0-1 completeness score used for ranking and the 'minimum quality' filter."""
    chars = sum(len(s) for s in steps)
    directions = 0.0 if chars < 20 else min(1.0, chars / 250)
    if ingredient_count == 0:
        ingredients = 0.0
    elif ingredient_count == 1:
        ingredients = 0.2
    elif ingredient_count == 2:
        ingredients = 0.5
    elif ingredient_count <= 25:
        ingredients = 1.0
    else:
        ingredients = 0.7
    title_ok = 1.0 if re.search(r"[A-Za-z]{3}", title) else 0.0
    score = (
        0.35 * directions
        + 0.35 * ingredients
        + 0.10 * coverage
        + 0.10 * has_time
        + 0.05 * has_servings
        + 0.05 * title_ok
    )
    if JUNK_TITLE.search(title):
        score *= 0.3
    return round(score, 3)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def process_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one raw CSV row into the fields stored in the ``recipes`` table."""
    raw_title = "" if row.get("title") is None else str(row.get("title"))
    title = clean_title(raw_title)
    raw_lines = parse_list_field(row.get("ingredients"))
    ner = parse_list_field(row.get("ner"))
    steps = parse_list_field(row.get("directions"))

    names, quantities, coverage = build_ingredients(raw_lines, ner)
    ingredient_text = " | ".join(names + [line.lower() for line in raw_lines])
    directions_text = " ".join(steps).lower()

    has_meat = _has(MEAT_RE, ingredient_text, MEAT_EXCEPTIONS)
    meal_type = classify_meal_type(title, ingredient_text, has_meat)
    is_dessert = meal_type == "dessert"
    flags = classify_diet(ingredient_text, directions_text, is_dessert)

    times = extract_times(steps, len(names))
    servings = extract_servings(raw_title, steps)
    active = (times["prep_time"] or 0) + (times["cook_time"] or 0) or None
    difficulty = classify_difficulty(
        steps, len(names), active, directions_text + " " + ingredient_text
    )

    link = row.get("link")
    if link and not str(link).startswith(("http://", "https://")):
        link = "https://" + str(link)

    return {
        "title": title,
        "link": link or None,
        "source": row.get("source") or None,
        "directions": "\n".join(steps),
        **times,
        "servings": servings,
        "difficulty_level": difficulty,
        "meal_type": meal_type,
        "ingredients_clean": names,
        "ingredients_original": raw_lines,
        "ingredient_quantities": quantities,
        "ingredient_categories": [categorize_ingredient(n) for n in names],
        "ingredient_count": len(names),
        **flags,
        "is_dessert": is_dessert,
        "has_complete_directions": sum(len(s) for s in steps) >= 50,
        "ingredient_quality_score": round(coverage, 3),
        "recipe_completeness_score": quality_score(
            title,
            steps,
            len(names),
            coverage,
            times["total_time"] is not None,
            servings is not None,
        ),
        "search_text": _squash(f"{title} {' '.join(names)}".lower()),
    }
