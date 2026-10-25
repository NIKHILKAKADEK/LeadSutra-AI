from pydantic import BaseModel, Field
from typing import List


class ProposalResult(BaseModel):
    business_summary: str
    identified_needs: List[str]
    proposed_solution: str
    deliverables: List[str]
    implementation_timeline: List[str]
    expected_benefits: List[str]
    pricing_suggestion: str
    next_steps: List[str]
    outreach_angle: str = ""
    email_subject_options: List[str] = Field(default_factory=list)
    personalized_email: str = ""
    call_opener: str = ""
    discovery_questions: List[str] = Field(default_factory=list)
