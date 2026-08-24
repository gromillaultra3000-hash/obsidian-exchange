from typing import List, Dict, Any

CAPABILITY_CATALOG: List[Dict[str, Any]] = [
    {"id": "text_reasoning", "title": "Text Reasoning", "description": "General text understanding and reasoning", "category": "reasoning", "defaultWeight": 0.8, "riskLevel": "low"},
    {"id": "code_analysis", "title": "Code Analysis", "description": "Analysis of code structure and quality", "category": "development", "defaultWeight": 0.9, "riskLevel": "low"},
    {"id": "data_analysis", "title": "Data Analysis", "description": "Analysis of data patterns and statistics", "category": "reasoning", "defaultWeight": 0.85, "riskLevel": "low"},
    {"id": "document_review", "title": "Document Review", "description": "Review of documents and text content", "category": "reasoning", "defaultWeight": 0.8, "riskLevel": "low"},
    {"id": "summarization", "title": "Summarization", "description": "Creating concise summaries of content", "category": "formatting", "defaultWeight": 0.7, "riskLevel": "low"},
    {"id": "planning", "title": "Planning", "description": "Creating plans and strategies", "category": "reasoning", "defaultWeight": 0.85, "riskLevel": "low"},
    {"id": "critique", "title": "Critique", "description": "Critical analysis and feedback", "category": "validation", "defaultWeight": 0.9, "riskLevel": "medium"},
    {"id": "validation", "title": "Validation", "description": "Validating outputs and decisions", "category": "validation", "defaultWeight": 0.9, "riskLevel": "low"},
    {"id": "risk_review", "title": "Risk Review", "description": "Assessment of risks and threats", "category": "safety", "defaultWeight": 0.95, "riskLevel": "high"},
    {"id": "format_checking", "title": "Format Checking", "description": "Checking format compliance", "category": "formatting", "defaultWeight": 0.6, "riskLevel": "low"},
    {"id": "fast_response", "title": "Fast Response", "description": "Quick responses for time-sensitive tasks", "category": "cost_latency", "defaultWeight": 0.5, "riskLevel": "low"},
    {"id": "low_cost_processing", "title": "Low Cost Processing", "description": "Cost-effective processing", "category": "cost_latency", "defaultWeight": 0.5, "riskLevel": "low"},
    {"id": "fallback_use", "title": "Fallback Use", "description": "Can be used as fallback provider", "category": "fallback", "defaultWeight": 0.4, "riskLevel": "medium"},
    {"id": "structured_output", "title": "Structured Output", "description": "Produces structured formatted output", "category": "formatting", "defaultWeight": 0.7, "riskLevel": "low"},
    {"id": "error_analysis", "title": "Error Analysis", "description": "Analysis of errors and failures", "category": "development", "defaultWeight": 0.85, "riskLevel": "medium"},
    {"id": "project_review", "title": "Project Review", "description": "Overall project assessment", "category": "development", "defaultWeight": 0.9, "riskLevel": "medium"},
    {"id": "patch_planning", "title": "Patch Planning", "description": "Planning patches and fixes", "category": "development", "defaultWeight": 0.85, "riskLevel": "medium"},
    {"id": "test_analysis", "title": "Test Analysis", "description": "Analysis of test results", "category": "development", "defaultWeight": 0.85, "riskLevel": "medium"},
    {"id": "policy_checking", "title": "Policy Checking", "description": "Checking against policies", "category": "safety", "defaultWeight": 0.9, "riskLevel": "high"},
    {"id": "decision_support", "title": "Decision Support", "description": "Supporting decision-making processes", "category": "reasoning", "defaultWeight": 0.9, "riskLevel": "medium"},
]


def get_capability_catalog() -> List[Dict[str, Any]]:
    return list(CAPABILITY_CATALOG)


def get_capability(capability_id: str) -> Dict[str, Any]:
    normalized = (capability_id or "").strip().lower()
    for cap in CAPABILITY_CATALOG:
        if cap["id"] == normalized:
            return dict(cap)
    return {}


def known_capability_ids() -> set[str]:
    return {cap["id"] for cap in CAPABILITY_CATALOG}
