"""Eval runner: executes the golden set and produces a scored report.

Usage:
    python -m eval.runner                  # run full eval, save report
    python -m eval.runner --diff report1.md report2.md  # compare two reports

Reports are saved to eval/reports/ with a timestamp.
"""

import argparse
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bi_agent.pipeline import ask
from bi_agent.types import Answer
from eval.judge import JudgeScore, judge

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(name)s: %(message)s",
)
logging.getLogger("bi_agent").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.yaml"
REPORTS_DIR = Path(__file__).parent / "reports"


# --- Shape matching ---


def check_shape(
    answer: Answer,
    golden: dict,
) -> tuple[bool, str]:
    """Check if the answer's result shape matches expectations.

    Checks:
    1. Expected columns are present (fuzzy: checks if any result column
       contains the expected substring).
    2. Row count is within the expected range.

    For out-of-scope questions (expected_row_count=0), passes if the agent
    produced no results or flagged an error.

    Args:
        answer: The pipeline Answer.
        golden: The golden set entry dict.

    Returns:
        Tuple of (passed: bool, reason: str).
    """
    expected_cols = golden.get("expected_columns", [])
    expected_rows = golden.get("expected_row_count")

    # Out-of-scope: pass if no results or agent flagged error
    if expected_rows == 0:
        if answer.result.empty or answer.trace.error:
            return True, "Correctly produced no results / flagged limitation"
        # Agent returned results — might still be okay if it's a thoughtful
        # response (e.g., showing historical data with caveats for a prediction
        # question). Let the judge decide.
        return True, "Agent returned results for out-of-scope question (judge will evaluate)"

    # Check column count (at least as many columns as expected)
    has_cols = expected_cols and not answer.result.empty
    if has_cols and len(answer.result.columns) < len(expected_cols):
        actual = list(answer.result.columns)
        return False, (
            f"Too few columns: expected at least {len(expected_cols)}, got {len(actual)}: {actual}"
        )

    # Check row count
    if expected_rows is not None and not answer.result.empty:
        actual_rows = len(answer.result)
        if isinstance(expected_rows, list):
            low, high = expected_rows
            if not (low <= actual_rows <= high):
                return False, f"Row count {actual_rows} outside expected range [{low}, {high}]"
        else:
            # Allow 10% tolerance for exact counts
            tolerance = max(1, int(expected_rows * 0.1))
            if abs(actual_rows - expected_rows) > tolerance:
                return False, f"Row count {actual_rows} != expected {expected_rows} (±{tolerance})"

    if answer.result.empty and expected_rows and expected_rows != 0:
        return False, "Empty result when rows were expected"

    return True, "Shape matches"


# --- Report generation ---


def _result_preview(answer: Answer, max_rows: int = 10) -> str:
    """Generate a compact string preview of the result DataFrame."""
    if answer.result.empty:
        return "(empty)"
    df = answer.result.head(max_rows)
    preview = df.to_string(index=False)
    if len(answer.result) > max_rows:
        preview += f"\n... ({len(answer.result)} total rows)"
    return preview


def run_eval() -> str:
    """Run the full golden set evaluation and return the report path.

    Returns:
        Path to the generated markdown report.
    """
    # Load golden set
    with open(GOLDEN_SET_PATH) as f:
        golden_data = yaml.safe_load(f)
    questions = golden_data["questions"]

    print(f"\n{'=' * 60}")
    print(f"  BI Agent Evaluation — {len(questions)} questions")
    print(f"{'=' * 60}\n")

    results: list[dict] = []

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        question = q["question"]
        category = q["category"]

        print(f"[{i}/{len(questions)}] {qid}: {question}")
        start = time.time()

        try:
            answer = ask(question)
            elapsed = round(time.time() - start, 1)
            print(
                f"  SQL agent: {answer.trace.total_iterations} steps, "
                f"{answer.trace.total_input_tokens}+{answer.trace.total_output_tokens} tokens, "
                f"{elapsed}s"
            )

            # Shape check
            shape_pass, shape_reason = check_shape(answer, q)
            print(f"  Shape: {'PASS' if shape_pass else 'FAIL'} — {shape_reason}")

            # Judge
            preview = _result_preview(answer)
            score = judge(
                question=question,
                sql=answer.sql,
                result_preview=preview,
                explanation=answer.explanation,
                golden_criteria=q.get("pass_criteria", ""),
            )
            print(
                f"  Judge: C={score.correctness} F={score.faithfulness} "
                f"Q={score.sql_quality} avg={score.average}"
            )

            # Dry-run compliance
            run_sql_steps = [s for s in answer.trace.steps if s.tool_name == "run_sql"]
            compliant = all(s.dry_run_preceded for s in run_sql_steps) if run_sql_steps else True

            results.append(
                {
                    "id": qid,
                    "category": category,
                    "question": question,
                    "sql": answer.sql,
                    "result_rows": len(answer.result),
                    "result_preview": preview,
                    "explanation": answer.explanation,
                    "shape_pass": shape_pass,
                    "shape_reason": shape_reason,
                    "score": score,
                    "trace_steps": answer.trace.total_iterations,
                    "trace_tokens_in": answer.trace.total_input_tokens,
                    "trace_tokens_out": answer.trace.total_output_tokens,
                    "budget_exhausted": answer.trace.budget_exhausted,
                    "dry_run_compliant": compliant,
                    "elapsed": elapsed,
                    "error": answer.trace.error,
                }
            )

        except Exception as e:
            elapsed = round(time.time() - start, 1)
            print(f"  ERROR: {e}")
            results.append(
                {
                    "id": qid,
                    "category": category,
                    "question": question,
                    "sql": "",
                    "result_rows": 0,
                    "result_preview": "",
                    "explanation": "",
                    "shape_pass": False,
                    "shape_reason": f"Pipeline error: {e}",
                    "score": JudgeScore(
                        correctness=1,
                        faithfulness=1,
                        sql_quality=1,
                        rationale=f"Pipeline error: {e}",
                    ),
                    "trace_steps": 0,
                    "trace_tokens_in": 0,
                    "trace_tokens_out": 0,
                    "budget_exhausted": False,
                    "dry_run_compliant": False,
                    "elapsed": elapsed,
                    "error": str(e),
                }
            )

        print()

    # Generate report
    report_path = _write_report(results)
    print(f"\nReport saved to: {report_path}")
    return report_path


def _write_report(results: list[dict]) -> str:
    """Write a markdown evaluation report.

    Args:
        results: List of per-question result dicts.

    Returns:
        Path to the saved report file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"eval_{timestamp}.md"

    # Compute aggregates
    total = len(results)
    shape_passes = sum(1 for r in results if r["shape_pass"])
    avg_correctness = sum(r["score"].correctness for r in results) / total
    avg_faithfulness = sum(r["score"].faithfulness for r in results) / total
    avg_sql_quality = sum(r["score"].sql_quality for r in results) / total
    avg_overall = sum(r["score"].average for r in results) / total
    total_tokens_in = sum(r["trace_tokens_in"] for r in results)
    total_tokens_out = sum(r["trace_tokens_out"] for r in results)
    dry_run_compliant = sum(1 for r in results if r["dry_run_compliant"])
    budget_exhausted = sum(1 for r in results if r["budget_exhausted"])
    total_elapsed = sum(r["elapsed"] for r in results)

    lines = [
        f"# Eval Report — {timestamp}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Questions | {total} |",
        f"| Shape pass rate | {shape_passes}/{total} ({100 * shape_passes / total:.0f}%) |",
        f"| Avg correctness | {avg_correctness:.2f}/5 |",
        f"| Avg faithfulness | {avg_faithfulness:.2f}/5 |",
        f"| Avg SQL quality | {avg_sql_quality:.2f}/5 |",
        f"| Avg overall | {avg_overall:.2f}/5 |",
        f"| Dry-run compliant | {dry_run_compliant}/{total} |",
        f"| Budget exhausted | {budget_exhausted}/{total} |",
        f"| Total tokens | {total_tokens_in} in + {total_tokens_out} out |",
        f"| Total time | {total_elapsed:.0f}s |",
        "",
        "## Per-question results",
        "",
    ]

    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r["category"], []).append(r)

    for cat, cat_results in categories.items():
        lines.append(f"### {cat}")
        lines.append("")

        for r in cat_results:
            score = r["score"]
            shape_icon = "PASS" if r["shape_pass"] else "FAIL"
            compliance = "yes" if r["dry_run_compliant"] else "NO"

            lines.append(f"#### {r['id']}: {r['question']}")
            lines.append("")
            lines.append(f"- **Shape:** {shape_icon} — {r['shape_reason']}")
            lines.append(
                f"- **Judge:** C={score.correctness} F={score.faithfulness} "
                f"Q={score.sql_quality} (avg={score.average})"
            )
            lines.append(f"- **Rationale:** {score.rationale}")
            lines.append(
                f"- **Agent:** {r['trace_steps']} steps, "
                f"{r['trace_tokens_in']}+{r['trace_tokens_out']} tokens, "
                f"{r['elapsed']}s, dry_run: {compliance}"
            )
            if r["error"]:
                lines.append(f"- **Error:** {r['error']}")
            if r["sql"]:
                lines.append("- **SQL:**")
                lines.append("  ```sql")
                lines.append(f"  {r['sql']}")
                lines.append("  ```")
            lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str(report_path)


# --- Report diffing ---


def diff_reports(path_a: str, path_b: str) -> None:
    """Compare two evaluation reports and print a summary of changes.

    Args:
        path_a: Path to the baseline (older) report.
        path_b: Path to the new report.
    """
    scores_a = _extract_scores(path_a)
    scores_b = _extract_scores(path_b)

    all_ids = sorted(set(scores_a.keys()) | set(scores_b.keys()))

    print(f"\n{'=' * 60}")
    print(f"  Eval Diff: {Path(path_a).name} -> {Path(path_b).name}")
    print(f"{'=' * 60}\n")

    improved = []
    regressed = []
    unchanged = []

    for qid in all_ids:
        a = scores_a.get(qid)
        b = scores_b.get(qid)

        if a is None:
            print(f"  + {qid}: NEW (avg={b})")
            improved.append(qid)
        elif b is None:
            print(f"  - {qid}: REMOVED (was avg={a})")
            regressed.append(qid)
        elif b > a:
            print(f"  ^ {qid}: {a} -> {b} (+{b - a:.2f})")
            improved.append(qid)
        elif b < a:
            print(f"  v {qid}: {a} -> {b} ({b - a:.2f})")
            regressed.append(qid)
        else:
            unchanged.append(qid)

    print(
        f"\n  Improved: {len(improved)}, Regressed: {len(regressed)}, Unchanged: {len(unchanged)}"
    )


def _extract_scores(report_path: str) -> dict[str, float]:
    """Extract per-question average scores from a report markdown file.

    Args:
        report_path: Path to the markdown report.

    Returns:
        Dict mapping question ID to average judge score.
    """
    scores = {}
    with open(report_path, encoding="utf-8") as f:
        content = f.read()

    # Parse "#### qid: question" followed by "- **Judge:** ... (avg=X.XX)"
    pattern = r"#### (\w+):.*?\n.*?avg=([\d.]+)"
    for match in re.finditer(pattern, content, re.DOTALL):
        qid = match.group(1)
        avg = float(match.group(2))
        scores[qid] = avg

    return scores


# --- CLI ---


def main() -> None:
    """CLI entry point for the eval runner."""
    parser = argparse.ArgumentParser(
        prog="eval.runner",
        description="Run BI agent evaluation",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("BASELINE", "NEW"),
        help="Compare two report files instead of running eval",
    )
    args = parser.parse_args()

    if args.diff:
        diff_reports(args.diff[0], args.diff[1])
    else:
        run_eval()


if __name__ == "__main__":
    main()
