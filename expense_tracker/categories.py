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

# Light-theme category colours as RGB tuples, for output that cannot use CSS
# variables (the PDF report). Keep in sync with --cat-* in style.css.
CATEGORY_PRINT_RGB = {
    "Food": (0x2A, 0x78, 0xD6),
    "Transportation": (0xEB, 0x68, 0x34),
    "Entertainment": (0x1B, 0xAF, 0x7A),
    "Shopping": (0xED, 0xA1, 0x00),
    "Bills": (0xE8, 0x7B, 0xA4),
    "Other": (0x00, 0x83, 0x00),
}
