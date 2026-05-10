"""LLM-as-judge for evaluating agent outputs.

Scores each agent response on three dimensions using a rubric:
  1. Correctness: Does the SQL + result correctly answer the question?
  2. Faithfulness: Does the answer address what was actually asked?
  3. SQL quality: Is the SQL clean, efficient, and idiomatic?

Each dimension is scored 1-5. The judge also provides a brief rationale.
"""

import json
import logging

from pydantic import BaseModel

from bi_agent.llm import complete

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """\
You are an expert SQL evaluator for a BI agent backed by the Olist Brazilian \
E-Commerce dataset (DuckDB). Your job is to score the agent's output on three \
dimensions.

## Scoring rubric

### Correctness (1-5)
5: SQL is correct and result fully answers the question.
4: SQL is correct, minor issues in presentation (e.g., column naming).
3: SQL runs but result is partially wrong (e.g., missing a filter, wrong aggregation).
2: SQL runs but answers a meaningfully different question.
1: SQL fails, returns empty/wrong results, or hallucinates data/columns.

### Faithfulness (1-5)
5: Answer directly addresses what was asked, with appropriate caveats.
4: Answer addresses the question but misses a nuance.
3: Answer is related but makes unsupported assumptions without stating them.
2: Answer drifts from the question significantly.
1: Answer is about something else entirely, or the agent refused without good reason.

### SQL quality (1-5)
5: Clean, readable, efficient SQL. Good use of aliases, appropriate joins.
4: Correct SQL with minor style issues.
3: SQL works but is unnecessarily complex or has redundant operations.
2: SQL is convoluted, hard to read, or uses anti-patterns.
1: SQL is broken or nonsensical.

## Special cases
- For out-of-scope questions (prediction, data that doesn't exist): if the agent \
correctly refuses or flags the limitation, score Correctness=5 and Faithfulness=5. \
SQL quality=3 if no SQL was generated (neutral).
- For ambiguous questions: if the agent states its assumption, don't penalize for \
picking one reasonable interpretation over another.

Respond with ONLY a JSON object, no markdown fencing:
{"correctness": N, "faithfulness": N, "sql_quality": N, "rationale": "..."}
"""


class JudgeScore(BaseModel):
    """Structured score from the LLM judge.

    Attributes:
        correctness: 1-5 score for result correctness.
        faithfulness: 1-5 score for addressing the actual question.
        sql_quality: 1-5 score for SQL readability and efficiency.
        rationale: Brief explanation of the scores.
    """

    correctness: int
    faithfulness: int
    sql_quality: int
    rationale: str

    @property
    def average(self) -> float:
        """Average of the three scores."""
        return round((self.correctness + self.faithfulness + self.sql_quality) / 3, 2)


def judge(
    question: str,
    sql: str,
    result_preview: str,
    explanation: str,
    *,
    golden_criteria: str = "",
) -> JudgeScore:
    """Score an agent's output using LLM-as-judge.

    Args:
        question: The original user question.
        sql: The SQL query the agent generated.
        result_preview: String preview of the result DataFrame.
        explanation: The agent's plain-English explanation.
        golden_criteria: Optional pass criteria from the golden set.

    Returns:
        JudgeScore with correctness, faithfulness, sql_quality, and rationale.

    Raises:
        ValueError: If the judge response cannot be parsed.
    """
    prompt_parts = [
        f"## Question\n{question}",
        f"## SQL\n```sql\n{sql}\n```" if sql else "## SQL\n(no SQL generated)",
        f"## Result\n{result_preview}" if result_preview else "## Result\n(no results)",
        f"## Explanation\n{explanation}" if explanation else "## Explanation\n(none)",
    ]
    if golden_criteria:
        prompt_parts.append(f"## Expected behavior\n{golden_criteria}")

    prompt = "\n\n".join(prompt_parts)

    raw = complete(
        prompt=prompt,
        system=_JUDGE_SYSTEM,
        temperature=0.0,
        max_tokens=512,
    )

    # Strip markdown fencing if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse judge response: {raw!r}") from e

    return JudgeScore(
        correctness=data["correctness"],
        faithfulness=data["faithfulness"],
        sql_quality=data["sql_quality"],
        rationale=data.get("rationale", ""),
    )
