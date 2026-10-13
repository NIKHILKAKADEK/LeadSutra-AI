from pydantic import BaseModel
from typing import List


class SWOTAnalysis(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]


class ResearchResult(BaseModel):
    business_summary: str
    products_services: List[str]
    target_audience: str
    pain_points: List[str]

    swot: SWOTAnalysis

    ideal_customer_profile: str
    decision_maker_identification: str
    sales_opportunities: List[str]

    provided_facts: List[str]
    reasonable_inferences: List[str]
    missing_information: List[str]