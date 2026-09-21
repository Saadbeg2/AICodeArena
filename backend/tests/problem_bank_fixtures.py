import json
from pathlib import Path


LEGACY_TWO_SUM = {
    "id": "two_sum",
    "title": "Two Sum",
    "type": "function",
    "language": "python",
    "description": "Return the indices of two numbers that add up to the target.",
    "function_signature": "def two_sum(numbers, target):",
    "files": [
        {
            "filename": "solution.py",
            "editable": True,
            "starter_content": "def two_sum(numbers, target):\n    pass\n",
        }
    ],
    "tests": {
        "visible": [
            {"input": {"numbers": [2, 7, 11, 15], "target": 9}, "expected": [0, 1]}
        ],
        "hidden": [
            {"input": {"numbers": [3, 2, 4], "target": 6}, "expected": [1, 2]},
            {"input": {"numbers": [3, 3], "target": 6}, "expected": [0, 1]},
        ],
    },
    "metadata": {
        "difficulty": "easy",
        "source": "custom",
        "tags": ["arrays", "hash-map"],
    },
}


LEGACY_FIX_USER_EMAIL = {
    "id": "fix_user_email",
    "title": "Fix User Email Bug",
    "type": "bug_fix",
    "language": "python",
    "description": "Fix get_user_email so it safely handles missing emails.",
    "files": [
        {
            "filename": "user.py",
            "editable": False,
            "starter_content": (
                "class User:\n"
                "    def __init__(self, name, email=None):\n"
                "        self.name = name\n"
                "        self.email = email\n"
            ),
        },
        {
            "filename": "service.py",
            "editable": True,
            "starter_content": (
                "def get_user_email(user):\n"
                "    return user.email.lower()\n"
            ),
        },
    ],
    "tests": {
        "visible": [],
        "hidden": [],
    },
    "metadata": {
        "difficulty": "easy",
        "source": "custom",
        "tags": ["python", "bug-fix"],
    },
}


LEGACY_MULTIPLY_NUMBERS = {
    "id": "multiply_numbers",
    "title": "Multiply Numbers",
    "type": "function",
    "language": "python",
    "description": "Return the product of two numbers.",
    "function_signature": "def multiply_numbers(a, b):",
    "files": [
        {
            "filename": "solution.py",
            "editable": True,
            "starter_content": "def multiply_numbers(a, b):\n    pass\n",
        }
    ],
    "tests": {
        "visible": [
            {"input": {"a": 2, "b": 3}, "expected": 6}
        ],
        "hidden": [
            {"input": {"a": -4, "b": 5}, "expected": -20}
        ],
    },
    "metadata": {
        "difficulty": "easy",
        "source": "custom",
        "tags": ["math"],
    },
}


LEGACY_TIC_TAC_TOE = {
    "id": "tic_tac_toe_board",
    "title": "Tic-Tac-Toe Board Layout",
    "type": "css_static_region",
    "language": "css",
    "description": "Complete the TODO region inside the #board rule.",
    "files": [
        {
            "filename": "index.html",
            "editable": False,
            "starter_content": (
                "<!DOCTYPE html>\n"
                "<html><head><link rel=\"stylesheet\" href=\"styles.css\"></head>"
                "<body><div id=\"board\"></div></body></html>\n"
            ),
        },
        {
            "filename": "styles.css",
            "editable": True,
            "starter_content": (
                "#board {\n"
                "    /* TODO: Add your solution here */\n"
                "}\n"
            ),
        },
    ],
    "tests": {
        "visible": [],
        "hidden": [],
    },
    "editable_region": {
        "file": "styles.css",
        "selector": "#board",
        "marker": "/* TODO: Add your solution here */",
    },
    "checks": {
        "required_selector": "#board",
        "required_declarations": [
            {"property": "display", "accepted_values": ["grid"]},
            {
                "property": "grid-template-columns",
                "accepted_values": [
                    "repeat(3, 100px)",
                    "repeat(3,100px)",
                    "100px 100px 100px",
                ],
            },
            {
                "property": "grid-template-rows",
                "accepted_values": [
                    "repeat(3, 100px)",
                    "repeat(3,100px)",
                    "100px 100px 100px",
                ],
            },
            {
                "property": "gap",
                "accepted_values": ["10px"],
                "alternate_properties": ["grid-gap", "column-gap"],
            },
            {
                "property": "justify-content",
                "accepted_values": ["center"],
            },
        ],
    },
    "metadata": {
        "difficulty": "easy",
        "source": "custom",
        "tags": ["css"],
    },
}


def write_problem_bank(problem_bank: Path, definitions: list) -> None:
    problem_bank.mkdir(parents=True, exist_ok=True)

    for definition in definitions:
        problem_key = definition["id"]
        file_path = problem_bank / f"{problem_key}.json"
        file_path.write_text(
            json.dumps(definition, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
