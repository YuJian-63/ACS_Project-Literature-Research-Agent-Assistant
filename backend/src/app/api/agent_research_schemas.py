from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class AgentResearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=8000)
    paper_ids: list[UUID] = Field(default_factory=list, max_length=20)
    allow_search: bool = True

    @field_validator("question")
    @classmethod
    def question_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A research question is required")
        return value

    @model_validator(mode="after")
    def evidence_path_required(self):
        if not self.paper_ids and not self.allow_search:
            raise ValueError("Select papers or allow search")
        return self
