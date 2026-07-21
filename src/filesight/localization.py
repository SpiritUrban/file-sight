"""Ukrainian labels for categories and common caption words.

Small hand-written dictionaries, no translation model. Any word without
an entry falls back to the original English word, so names stay usable
even when a term is missing here.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("en", "uk")

# Internal category id -> Ukrainian label
CATEGORY_LABELS_UK = {
    "people": "люди",
    "animals": "тварини",
    "nature": "природа",
    "food": "їжа",
    "vehicles": "транспорт",
    "documents": "документи",
    "screenshots": "скриншоти",
    "code": "код",
    "products": "товари",
    "buildings": "будівлі",
    "travel": "подорожі",
    "sports": "спорт",
    "events": "події",
    "art": "мистецтво",
    "memes": "меми",
    "medical": "медицина",
    "other": "інше",
}

# Common nouns/objects seen in BLIP captions
WORDS_UK = {
    # animals
    "dog": "пес", "puppy": "цуценя", "cat": "кіт", "kitten": "кошеня",
    "bird": "птах", "horse": "кінь", "cow": "корова", "fish": "риба",
    "rabbit": "кролик", "animal": "тварина", "bear": "ведмідь",
    # people
    "man": "чоловік", "woman": "жінка", "boy": "хлопець", "girl": "дівчина",
    "child": "дитина", "children": "діти", "people": "люди",
    "person": "людина", "family": "сім'я", "group": "група",
    "portrait": "портрет", "baby": "немовля",
    # nature
    "snow": "сніг", "forest": "ліс", "mountain": "гора", "river": "річка",
    "lake": "озеро", "sea": "море", "tree": "дерево", "trees": "дерева",
    "flower": "квітка", "sky": "небо", "sunset": "захід", "beach": "пляж",
    "grass": "трава", "water": "вода", "cloud": "хмара", "field": "поле",
    # vehicles
    "car": "автомобіль", "truck": "вантажівка", "bus": "автобус",
    "train": "потяг", "airplane": "літак", "motorcycle": "мотоцикл",
    "bicycle": "велосипед", "boat": "човен",
    # food
    "food": "їжа", "meal": "страва", "plate": "тарілка", "pizza": "піца",
    "bread": "хліб", "cake": "торт", "meat": "м'ясо", "fruit": "фрукт",
    "vegetable": "овоч", "coffee": "кава", "drink": "напій",
    # places / objects
    "city": "місто", "street": "вулиця", "building": "будівля",
    "house": "будинок", "room": "кімната", "table": "стіл",
    "chair": "стілець", "window": "вікно", "door": "двері",
    "sofa": "диван", "park": "парк", "road": "дорога", "bridge": "міст",
    # screens / code
    "screen": "екран", "screenshot": "скриншот", "computer": "комп'ютер",
    "monitor": "монітор", "phone": "телефон", "laptop": "ноутбук",
    "code": "код", "editor": "редактор", "terminal": "термінал",
    "browser": "браузер", "application": "застосунок", "website": "сайт",
    "document": "документ", "text": "текст", "book": "книга",
    # colors / adjectives
    "black": "чорний", "white": "білий", "red": "червоний",
    "blue": "синій", "green": "зелений", "yellow": "жовтий",
    "orange": "помаранчевий", "brown": "коричневий", "grey": "сірий",
    "gray": "сірий", "small": "малий", "large": "великий", "big": "великий",
    "old": "старий", "new": "новий", "young": "молодий",
    # actions
    "running": "біжить", "walking": "йде", "sitting": "сидить",
    "standing": "стоїть", "playing": "грає", "jumping": "стрибає",
    "sleeping": "спить", "eating": "їсть", "drinking": "п'є",
    "flying": "летить", "swimming": "пливе", "riding": "їде",
    "holding": "тримає", "looking": "дивиться", "smiling": "усміхається",
    "working": "працює", "driving": "керує", "reading": "читає",
    "cooking": "готує", "dancing": "танцює", "climbing": "лізе",
}


def category_label(category: str, language: str) -> str:
    """Display/file label for an internal category id."""
    if language == "uk":
        return CATEGORY_LABELS_UK.get(category, category)
    return category


def localize_word(word: str, language: str) -> str:
    """Translate one word, falling back to the original when unknown."""
    if language != "uk":
        return word
    return WORDS_UK.get(word.lower(), word)


def localize_phrase(phrase: str, language: str) -> str:
    """Translate each word of a phrase independently."""
    if language != "uk" or not phrase:
        return phrase
    return " ".join(localize_word(word, language) for word in phrase.split())
