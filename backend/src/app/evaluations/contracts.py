from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RUBRIC_VERSION = "research-v1"
PROMPT_VERSION = "deepseek-judge-v2"
WEIGHTS = {"grounded_correctness": 30, "citation_support": 30, "task_completion": 20,
    "analysis_quality": 15, "clarity": 5}
ShortText = Annotated[str, Field(min_length=1, max_length=2000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Dimension(StrictModel):
    score: float | None = Field(ge=0, le=5, allow_inf_nan=False)
    reason: ShortText


class Dimensions(StrictModel):
    grounded_correctness: Dimension
    citation_support: Dimension
    task_completion: Dimension
    analysis_quality: Dimension
    clarity: Dimension


class Issue(StrictModel):
    severity: Literal["minor", "major", "critical"]
    code: Literal["unsupported_claim", "contradiction", "missing_citation", "incorrect_attribution",
        "incomplete_answer", "invalid_comparison", "unclear_expression", "other"]
    message: ShortText
    citation_keys: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(max_length=30)
    answer_excerpt: str = Field(max_length=1000)


class JudgeReport(StrictModel):
    assessment: Literal["scored", "insufficient_evidence"]
    summary: ShortText
    dimensions: Dimensions
    issues: list[Issue] = Field(max_length=30)
    suggestions: list[ShortText] = Field(max_length=10)

    @model_validator(mode="after")
    def consistent_assessment(self):
        scores = [getattr(self.dimensions, key).score for key in WEIGHTS]
        if self.assessment == "scored" and any(score is None for score in scores):
            raise ValueError("Scored assessments require all dimensions")
        if self.assessment == "insufficient_evidence" and any(score is not None for score in scores):
            raise ValueError("Insufficient evidence cannot have numerical scores")
        return self


def validate_report(payload: dict, citation_keys: set[str]) -> JudgeReport:
    report = JudgeReport.model_validate(payload)
    if any(key not in citation_keys for issue in report.issues for key in issue.citation_keys):
        raise ValueError("Judge referenced an unknown citation")
    return report


def weighted_score(report: JudgeReport) -> float | None:
    if report.assessment == "insufficient_evidence":
        return None
    total = sum(Decimal(str(getattr(report.dimensions, key).score)) * weight / 5 for key, weight in WEIGHTS.items())
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class EvaluationFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)
