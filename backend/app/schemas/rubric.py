"""
Pydantic models for rubric documents.
"""
from pydantic import BaseModel, Field


class RubricComponent(BaseModel):
    name: str
    marks: float
    model_answer: str = Field("", description="Ideal answer for this specific component or question")
    mark_bands: str = Field("", description="Explicit descriptors for scoring (e.g., '4-5: flawless, 2-3: arithmetic slip')")
    part: str = Field("Part A", description="Examination section or part (e.g. 'Part A', 'Part B', 'Part C')")
    is_compulsory: bool = Field(True, description="Whether this question is compulsory")
    choice_group: str = Field("", description="Group identifier for choice alternatives (e.g. 'part_b_choice', 'part_c_choice')")
    choice_option: str = Field("", description="Choice option identifier (e.g. '2c', '2d', 'Q3', 'Q4')")


class CreateRubricRequest(BaseModel):
    components: list[RubricComponent]


class RubricResponse(BaseModel):
    id: str = Field(..., alias="_id")
    components: list[RubricComponent]

    class Config:
        populate_by_name = True


class RubricListResponse(BaseModel):
    total: int
    rubrics: list[RubricResponse]
