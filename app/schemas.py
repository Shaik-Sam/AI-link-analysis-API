from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Platform = Literal["Google", "Facebook", "Instagram", "LinkedIn", "X"]

PLATFORM_ALIASES = {
    "google": "Google",
    "google search": "Google",
    "facebook": "Facebook",
    "fb": "Facebook",
    "meta": "Facebook",
    "instagram": "Instagram",
    "ig": "Instagram",
    "linkedin": "LinkedIn",
    "x": "X",
    "twitter": "X",
    "x (twitter)": "X",
    "x/twitter": "X",
}


class LinkAnalysisRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048, examples=["https://example.com"])
    refresh: bool = Field(default=False, description="Bypass the cache and re-run the analysis.")


class BrandInfo(BaseModel):
    name: str
    category: str
    summary: str


class BrandComparison(BaseModel):
    main_service: str = ""
    target_market: str = ""
    key_strength: str = ""
    opportunity: str = ""


class Competitor(BaseModel):
    name: str
    website: Optional[str] = None
    main_service: str = ""
    target_market: str = ""
    key_strength: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    opportunity: str = ""
    source: str = "ai_generated_suggestion"
    domain_resolves: Optional[bool] = None


class ComparisonRow(BaseModel):
    name: str
    is_your_brand: bool
    main_service: str = ""
    target_market: str = ""
    key_strength: str = ""
    opportunity: str = ""


class CompetitorAnalysis(BaseModel):
    brand_overview: str
    main_category: str = ""
    main_products_services: list[str] = Field(default_factory=list)
    your_brand: BrandComparison = Field(default_factory=BrandComparison)
    competitors: list[Competitor] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    comparison_table: list[ComparisonRow] = Field(default_factory=list)
    note: str = ""


class SearchQuery(BaseModel):
    query: str
    platforms: list[Platform]
    intent: str
    business_relevance: str = ""
    target_audience: str = ""
    search_volume: Optional[int] = None

    @field_validator("platforms", mode="before")
    @classmethod
    def normalise_platforms(cls, value):
        if isinstance(value, str):
            value = [value]
        result: list[str] = []
        for item in value or []:
            mapped = PLATFORM_ALIASES.get(str(item).strip().lower())
            if mapped and mapped not in result:
                result.append(mapped)
        if not result:
            raise ValueError("at least one supported platform is required")
        return result


class SupportingContent(BaseModel):
    service_landing_pages: list[str] = Field(default_factory=list)
    industry_pages: list[str] = Field(default_factory=list)
    faqs: list[str] = Field(default_factory=list)
    blog_topics: list[str] = Field(default_factory=list)
    location_pages: list[str] = Field(default_factory=list)
    supporting_articles: list[str] = Field(default_factory=list)


class SeoImprovements(BaseModel):
    primary_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    long_tail_keywords: list[str] = Field(default_factory=list)
    business_keywords: list[str] = Field(default_factory=list)
    recommended_title: str
    title_structure: str = ""
    title_length: int = 0
    meta_description: str
    meta_description_keywords: list[str] = Field(default_factory=list)
    meta_description_length: int = 0
    supporting_content: SupportingContent = Field(default_factory=SupportingContent)
    current_title: str = ""
    current_meta_description: str = ""


class Service(BaseModel):
    name: str
    description: str
    target_industry: str = ""
    target_customer: str = ""
    main_benefit: str = ""
    source: Literal["website", "inferred"] = "inferred"

    @field_validator("source", mode="before")
    @classmethod
    def normalise_source(cls, value):
        return "website" if "website" in str(value).lower() else "inferred"


class CustomerProfile(BaseModel):
    profile: str
    description: str = ""


class MarketingSegment(BaseModel):
    segment: str
    business_type: str = ""
    requirement: str = ""


class TargetAudience(BaseModel):
    primary_audience: list[str] = Field(default_factory=list)
    secondary_audience: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    business_types: list[str] = Field(default_factory=list)
    customer_profiles: list[CustomerProfile] = Field(default_factory=list)
    geographic_focus: str = ""
    customer_needs: list[str] = Field(default_factory=list)
    challenges: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    recommended_segments: list[MarketingSegment] = Field(default_factory=list)


class LLMAnalysis(BaseModel):
    brand: BrandInfo
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQuery]
    seo_improvements: SeoImprovements
    top_services: list[Service]
    target_audience: TargetAudience

    @field_validator("target_search_queries")
    @classmethod
    def require_five_queries(cls, value):
        if len(value) < 5:
            raise ValueError("target_search_queries must contain exactly 5 items")
        return value[:5]

    @field_validator("top_services")
    @classmethod
    def require_five_services(cls, value):
        if len(value) < 5:
            raise ValueError("top_services must contain exactly 5 items")
        return value[:5]


class Analysis(BaseModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQuery]
    seo_improvements: SeoImprovements
    top_services: list[Service]
    target_audience: TargetAudience


class AnalysisMeta(BaseModel):
    provider: str
    model: str
    cached: bool = False
    pages_analyzed: list[str] = Field(default_factory=list)
    content_chars: int = 0
    content_truncated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Optional[float] = None
    elapsed_ms: int = 0
    notes: list[str] = Field(default_factory=list)


class LinkAnalysisResponse(BaseModel):
    success: bool = True
    website: str
    brand: BrandInfo
    analysis: Analysis
    meta: AnalysisMeta


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
