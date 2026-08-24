from typing import List, Dict, Any

ROLE_CATALOG: List[Dict[str, Any]] = [
    {"roleId": "planner", "title": "Planner", "description": "Plans tasks and strategies", "requiredCapabilities": ["planning", "text_reasoning"], "optionalCapabilities": ["decision_support"], "defaultPriority": 8, "canApprove": True, "canReject": False, "canVeto": False, "canFallback": False, "riskWeight": 0.5},
    {"roleId": "reviewer", "title": "Reviewer", "description": "Reviews outputs and provides feedback", "requiredCapabilities": ["text_reasoning"], "optionalCapabilities": ["critique", "validation"], "defaultPriority": 7, "canApprove": True, "canReject": True, "canVeto": False, "canFallback": False, "riskWeight": 0.4},
    {"roleId": "critic", "title": "Critic", "description": "Provides critical analysis", "requiredCapabilities": ["critique"], "optionalCapabilities": ["validation", "error_analysis"], "defaultPriority": 7, "canApprove": False, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.7},
    {"roleId": "validator", "title": "Validator", "description": "Validates decisions and outputs", "requiredCapabilities": ["validation"], "optionalCapabilities": ["format_checking", "critique"], "defaultPriority": 8, "canApprove": True, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.6},
    {"roleId": "risk_checker", "title": "Risk Checker", "description": "Assesses and manages risks", "requiredCapabilities": ["risk_review"], "optionalCapabilities": ["policy_checking", "decision_support"], "defaultPriority": 9, "canApprove": True, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.9},
    {"roleId": "formatter", "title": "Formatter", "description": "Formats and structures outputs", "requiredCapabilities": ["format_checking", "structured_output"], "optionalCapabilities": ["summarization"], "defaultPriority": 5, "canApprove": False, "canReject": False, "canVeto": False, "canFallback": False, "riskWeight": 0.2},
    {"roleId": "final_resolver", "title": "Final Resolver", "description": "Makes final decisions on conflicts", "requiredCapabilities": ["decision_support", "text_reasoning"], "optionalCapabilities": ["risk_review", "validation"], "defaultPriority": 10, "canApprove": True, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.8},
    {"roleId": "fallback_provider", "title": "Fallback Provider", "description": "Provides fallback responses when primary providers fail", "requiredCapabilities": ["fallback_use", "text_reasoning"], "optionalCapabilities": ["fast_response", "low_cost_processing"], "defaultPriority": 1, "canApprove": False, "canReject": False, "canVeto": False, "canFallback": True, "riskWeight": 0.3},
    {"roleId": "code_reviewer", "title": "Code Reviewer", "description": "Reviews code for quality and issues", "requiredCapabilities": ["code_analysis"], "optionalCapabilities": ["critique", "validation", "error_analysis"], "defaultPriority": 8, "canApprove": True, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.6},
    {"roleId": "document_reviewer", "title": "Document Reviewer", "description": "Reviews documents and text", "requiredCapabilities": ["document_review"], "optionalCapabilities": ["summarization", "critique"], "defaultPriority": 6, "canApprove": True, "canReject": True, "canVeto": False, "canFallback": False, "riskWeight": 0.3},
    {"roleId": "data_analyst", "title": "Data Analyst", "description": "Analyzes data and provides insights", "requiredCapabilities": ["data_analysis"], "optionalCapabilities": ["text_reasoning", "planning"], "defaultPriority": 7, "canApprove": True, "canReject": False, "canVeto": False, "canFallback": False, "riskWeight": 0.4},
    {"roleId": "project_reviewer", "title": "Project Reviewer", "description": "Reviews projects and improvement plans", "requiredCapabilities": ["project_review"], "optionalCapabilities": ["planning", "error_analysis", "code_analysis"], "defaultPriority": 8, "canApprove": True, "canReject": True, "canVeto": False, "canFallback": False, "riskWeight": 0.6},
    {"roleId": "patch_planner", "title": "Patch Planner", "description": "Plans patches and fixes", "requiredCapabilities": ["patch_planning"], "optionalCapabilities": ["code_analysis", "planning", "error_analysis"], "defaultPriority": 7, "canApprove": True, "canReject": False, "canVeto": False, "canFallback": False, "riskWeight": 0.5},
    {"roleId": "test_checker", "title": "Test Checker", "description": "Checks test results and failures", "requiredCapabilities": ["test_analysis"], "optionalCapabilities": ["error_analysis", "code_analysis"], "defaultPriority": 7, "canApprove": True, "canReject": True, "canVeto": False, "canFallback": False, "riskWeight": 0.5},
    {"roleId": "policy_checker", "title": "Policy Checker", "description": "Checks compliance with policies", "requiredCapabilities": ["policy_checking"], "optionalCapabilities": ["risk_review", "validation"], "defaultPriority": 9, "canApprove": True, "canReject": True, "canVeto": True, "canFallback": False, "riskWeight": 0.9},
]


def get_role_catalog() -> List[Dict[str, Any]]:
    return list(ROLE_CATALOG)


def get_role(role_id: str) -> Dict[str, Any]:
    normalized = (role_id or "").strip().lower()
    for role in ROLE_CATALOG:
        if role["roleId"] == normalized:
            return dict(role)
    return {}


def known_role_ids() -> set[str]:
    return {role["roleId"] for role in ROLE_CATALOG}
