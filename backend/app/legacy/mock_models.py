"""
Legacy mock AI model responses retained for historical reference.

These mock implementations are NOT registered in the active application.
They are preserved only so older experiments, documentation notes, and
isolated legacy tests can still reference the original demo behavior.
"""

from typing import Dict


MOCK_AI_GOOD_RESPONSE = """def two_sum(numbers: list[int], target: int) -> list[int]:
    seen = {}

    for index, number in enumerate(numbers):
        needed = target - number

        if needed in seen:
            return [seen[needed], index]

        seen[number] = index

    return []
"""

MOCK_AI_BAD_RESPONSE = """def two_sum(numbers: list[int], target: int) -> list[int]:
    return [0, 0]"""

MOCK_AI_SLOW_RESPONSE = """def two_sum(numbers: list[int], target: int) -> list[int]:
    while True:
        pass
"""

MOCK_EMAIL_GOOD_RESPONSE = """def get_user_email(user):
    if user.email is None:
        return None
    return user.email.lower()
"""

MOCK_EMAIL_BAD_RESPONSE = """def get_user_email(user):
    return user.email.lower()"""

MOCK_EMAIL_SLOW_RESPONSE = """def get_user_email(user):
    while True:
        pass
"""

MOCK_MULTIPLY_GOOD_RESPONSE = """def multiply_numbers(a, b):
    return a * b"""

MOCK_MULTIPLY_BAD_RESPONSE = """def multiply_numbers(a, b):
    return a + b"""

MOCK_MULTIPLY_SLOW_RESPONSE = """def multiply_numbers(a, b):
    while True:
        pass
"""

MOCK_CSS_GOOD_RESPONSE = """display: grid;
grid-template-columns: 100px 100px 100px;
grid-template-rows: 100px 100px 100px;
grid-gap: 10px;
justify-content: center;"""

MOCK_CSS_BAD_RESPONSE = """display: block;
grid-template-columns: 100px 100px;
grid-gap: 5px;"""

MOCK_CSS_SLOW_RESPONSE = """/* AICODEARENA_SLOW */
display: grid;
grid-template-columns: 100px 100px 100px;
grid-template-rows: 100px 100px 100px;
grid-gap: 10px;
justify-content: center;"""

MOCK_STARTING_LINEUP_GOOD_RESPONSE = """<!DOCTYPE html>
<html lang="en">
<head>
   <title>Starting Lineup</title>
   <link rel="stylesheet" href="styles.css">
</head>
<body>
   <h1>Starting Lineup</h1>
   <form method="POST" action="https://wp.zybooks.com/form-viewer.php">
      <p>
         <fieldset>
            <legend>Status:</legend>
            <input type="radio" id="draft" name="status" value="Draft">
            <label for="draft">Draft</label>
            <input type="radio" id="final" name="status" value="Final" checked>
            <label for="final">Final</label>
         </fieldset>
      </p>
      <p>
         <label for="gameDate">Game date:</label>
         <select id="gameDate" name="gameDate">
            <option value="March 20">March 20</option>
            <option value="March 24">March 24</option>
            <option value="April 2">April 2</option>
            <option value="April 6">April 6</option>
            <option value="April 13">April 13</option>
         </select>
      </p>
      <p>
         <fieldset>
            <legend>Players:</legend>
            <input type="checkbox" id="aarav" name="player" value="Aarav Agarwal">
            <label for="aarav">Aarav Agarwal</label>
            <input type="checkbox" id="ava" name="player" value="Ava Johnson">
            <label for="ava">Ava Johnson</label>
            <input type="checkbox" id="julio" name="player" value="Julio Ortiz">
            <label for="julio">Julio Ortiz</label>
            <input type="checkbox" id="liam" name="player" value="Liam Rubio">
            <label for="liam">Liam Rubio</label>
            <input type="checkbox" id="emma" name="player" value="Emma Witherspoon">
            <label for="emma">Emma Witherspoon</label>
         </fieldset>
      </p>
      <p>
         <button type="submit">Submit</button>
      </p>
   </form>
</body>
</html>
"""

MOCK_STARTING_LINEUP_BAD_RESPONSE = """<!DOCTYPE html>
<html lang="en">
<head>
   <title>Starting Lineup</title>
</head>
<body>
   <h1>Starting Lineup</h1>
   <form method="GET" action="/submit">
      <p>This form is incomplete.</p>
   </form>
</body>
</html>
"""

MOCK_TIC_TAC_TOE_FULL_FILE_GOOD_RESPONSE = """body {
   font-family: Roboto, Helvetica, sans-serif;
   text-align: center;
}

#board {
   font: 85px arial, sans-serif;
   margin: 3px;
   display: grid;
   grid-template-columns: 100px 100px 100px;
   grid-template-rows: 100px 100px 100px;
   grid-gap: 10px;
   justify-content: center;
}

#board > div {
   border: 1px solid LightSkyBlue;
   text-align: center;
}

.x {
   color: red;
}

.o {
   color: blue;
}
"""

MOCK_TIC_TAC_TOE_FULL_FILE_BAD_RESPONSE = """body {
   font-family: Roboto, Helvetica, sans-serif;
   text-align: center;
}

#board {
   font: 85px arial, sans-serif;
   margin: 3px;
   display: block;
   color: red;
}

#board > div {
   border: 1px solid LightSkyBlue;
   text-align: center;
}

.x {
   color: red;
}

.o {
   color: blue;
}
"""

MOCK_NOTABLE_QUOTES_GOOD_RESPONSE = """window.addEventListener("DOMContentLoaded", function () {
   document.querySelector("#fetchQuotesBtn").addEventListener("click", function () {
      const topicDropdown = document.querySelector("#topicSelection");
      const selectedTopic = topicDropdown.options[topicDropdown.selectedIndex].value;
      const countDropdown = document.querySelector("#countSelection");
      const selectedCount = countDropdown.options[countDropdown.selectedIndex].value;

      fetchQuotes(selectedTopic, selectedCount);
   });
});

function showAnonymousQuotes(count) {
   let html = "<ol>";
   for (let c = 1; c <= count; c++) {
      html += `<li>Quote ${c} - Anonymous</li>`;
   }
   html += "</ol>";

   document.querySelector("#quotes").innerHTML = html;
}

function fetchQuotes(topic, count) {
   const xhr = new XMLHttpRequest();
   xhr.open("GET", `https://wp.zybooks.com/quotes.php?topic=${topic}&count=${count}`);
   xhr.responseType = "json";
   xhr.addEventListener("load", responseReceivedHandler);
   xhr.send();
}

function responseReceivedHandler() {
   const quotesElement = document.querySelector("#quotes");

   if (this.response && this.response.error) {
      quotesElement.innerHTML = `<p>${this.response.error}</p>`;
      return;
   }

   let html = "<ol>";
   for (const quote of this.response) {
      html += `<li>${quote.quote} - ${quote.source}</li>`;
   }
   html += "</ol>";
   quotesElement.innerHTML = html;
}
"""

MOCK_NOTABLE_QUOTES_BAD_RESPONSE = """window.addEventListener("DOMContentLoaded", function () {
   document.querySelector("#fetchQuotesBtn").addEventListener("click", function () {
      fetchQuotes("love", 1);
   });
});

function showAnonymousQuotes(count) {
   document.querySelector("#quotes").innerHTML = "<p>Anonymous only</p>";
}

function fetchQuotes(topic, count) {
   showAnonymousQuotes(count);
}

function responseReceivedHandler() {
   document.querySelector("#quotes").innerHTML = "<p>Error</p>";
}
"""

MOCK_STARTING_LINEUP_SLOW_RESPONSE = """<!DOCTYPE html>
<html lang="en">
<head>
   <title>Starting Lineup</title>
</head>
<body>
   <!-- AICODEARENA_BROWSER_SLOW -->
   <script>while (true) {}</script>
</body>
</html>
"""

MOCK_TIC_TAC_TOE_SLOW_RESPONSE = """/* AICODEARENA_BROWSER_SLOW */
#board {
   display: grid;
}
"""

MOCK_NOTABLE_QUOTES_SLOW_RESPONSE = """// AICODEARENA_BROWSER_SLOW
while (true) {}
"""

MOCK_FORMAT_BAD_RESPONSE = """Here is the solution:

```python
def two_sum(numbers: list[int], target: int) -> list[int]:
    seen = {}

    for index, number in enumerate(numbers):
        needed = target - number

        if needed in seen:
            return [seen[needed], index]

        seen[number] = index

    return []
```
"""


def responses_for_prompt(problem_prompt: str) -> Dict[str, str]:
    if "Title: Fix User Email Bug" in problem_prompt:
        return {
            "good": MOCK_EMAIL_GOOD_RESPONSE,
            "bad": MOCK_EMAIL_BAD_RESPONSE,
            "slow": MOCK_EMAIL_SLOW_RESPONSE,
            "format_bad": """```python
def get_user_email(user):
    if user.email is None:
        return None
    return user.email.lower()
```""",
        }

    if "Title: Multiply Numbers" in problem_prompt:
        return {
            "good": MOCK_MULTIPLY_GOOD_RESPONSE,
            "bad": MOCK_MULTIPLY_BAD_RESPONSE,
            "slow": MOCK_MULTIPLY_SLOW_RESPONSE,
            "format_bad": """python
def multiply_numbers(a, b):
    return a * b
""",
        }

    if "Title: Starting Lineup" in problem_prompt:
        return {
            "good": MOCK_STARTING_LINEUP_GOOD_RESPONSE,
            "bad": MOCK_STARTING_LINEUP_BAD_RESPONSE,
            "slow": MOCK_STARTING_LINEUP_SLOW_RESPONSE,
            "format_bad": """```html
<!DOCTYPE html>
<html><body><p>Bad format</p></body></html>
```""",
        }

    if (
        "Title: Tic-Tac-Toe Board Layout" in problem_prompt
        and "Required submission file: styles.css" in problem_prompt
    ):
        return {
            "good": MOCK_TIC_TAC_TOE_FULL_FILE_GOOD_RESPONSE,
            "bad": MOCK_TIC_TAC_TOE_FULL_FILE_BAD_RESPONSE,
            "slow": MOCK_TIC_TAC_TOE_SLOW_RESPONSE,
            "format_bad": """Here is styles.css:
#board {
   display: grid;
}
""",
        }

    if "Title: Notable Quotes" in problem_prompt:
        return {
            "good": MOCK_NOTABLE_QUOTES_GOOD_RESPONSE,
            "bad": MOCK_NOTABLE_QUOTES_BAD_RESPONSE,
            "slow": MOCK_NOTABLE_QUOTES_SLOW_RESPONSE,
            "format_bad": """```javascript
function fetchQuotes() {}
```""",
        }

    if "Title: Tic-Tac-Toe Board Layout" in problem_prompt:
        return {
            "good": MOCK_CSS_GOOD_RESPONSE,
            "bad": MOCK_CSS_BAD_RESPONSE,
            "slow": MOCK_CSS_SLOW_RESPONSE,
            "format_bad": """```css
display: grid;
grid-template-columns: 100px 100px 100px;
```""",
        }

    return {
        "good": MOCK_AI_GOOD_RESPONSE,
        "bad": MOCK_AI_BAD_RESPONSE,
        "slow": MOCK_AI_SLOW_RESPONSE,
        "format_bad": MOCK_FORMAT_BAD_RESPONSE,
    }
