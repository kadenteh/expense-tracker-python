CATEGORY_COLOR_VAR = {
    "Food": "--cat-food",
    "Transportation": "--cat-transportation",
    "Entertainment": "--cat-entertainment",
    "Shopping": "--cat-shopping",
    "Bills": "--cat-bills",
    "Other": "--cat-other",
}


def category_color(category: str) -> str:
    var = CATEGORY_COLOR_VAR.get(category, "--cat-other")
    return f"var({var})"
