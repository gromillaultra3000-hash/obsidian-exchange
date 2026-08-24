import uuid
from lumi.app.schemas.decision import StructuredDecision


def build_decision(**kwargs) -> StructuredDecision:
    kwargs.setdefault("decisionId", str(uuid.uuid4()))
    return StructuredDecision(**kwargs)
