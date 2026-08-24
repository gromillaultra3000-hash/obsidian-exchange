import re
import uuid
from lumi.app.schemas.dialog import DialogMessage, DialogCommand
from lumi.app.schemas.task import TaskRequest


class CommandParser:
    def __init__(self):
        self.patterns = {
            "explain_decision": ["объясни решение", "почему такое решение", "why decision", "explain decision", "почему wait", "почему safe_default", "объясни"],
            "show_history": ["покажи историю", "history", "история решений", "последние решения", "show history"],
            "show_status": ["статус", "status", "что подключено", "runtime", "состояние"],
            "approval_response": ["approve", "reject", "одобряю", "отклоняю", "согласен", "не согласен", "подтверждаю", "отказываю"],
            "register_provider_help": ["подключить provider", "добавить провайдера", "api key", "ключ", "register provider", "add provider", "подключи провайдера", "подключи ИИ", "connect provider", "provider setup", "test connection", "show providers"],
            "register_action_help": ["добавить action", "зарегистрировать действие", "разрешить действие", "register action", "add action"],
            "project_scan": ["проверь проект", "просканируй проект", "analyze project", "scan project", "check project", "проверь код", "проанализируй проект"],
            "show_project_summary": ["покажи проект", "project summary", "структура проекта", "project status", "что с проектом"],
            "show_improvement_plan": ["план улучшений", "improvement plan", "что улучшить", "предложения по улучшению", "improvement suggestions"],
            "patch_preview": ["подготовь патч", "сделай patch preview", "подготовь исправление", "prepare patch", "patch preview", "diff preview", "покажи патч", "сделай патч"],
            "show_diff_preview": ["покажи diff", "покажи изменения", "show diff", "diff"],
            "show_test_plan": ["план тестов", "test plan", "как проверить", "как тестировать"],
            "show_rollback_plan": ["как откатить", "rollback", "план отката", "откат"],
            "create_sandbox": ["создай sandbox", "создай песочницу", "sandbox workspace", "create sandbox", "песочница"],
            "sandbox_test": ["запусти sandbox test", "проверь в песочнице", "sandbox test", "controlled test", "dry-run tests", "запусти тесты в песочнице"],
            "apply_preview_to_sandbox": ["примени preview в sandbox", "apply preview to sandbox", "применить diff в песочнице", "применить изменения в песочнице"],
            "prepare_apply_package": ["подготовь apply package", "подготовь применение", "prepare apply", "prepare apply package", "подготовь пакет применения"],
            "show_apply_package": ["покажи apply package", "show apply package", "пакет применения", "apply package"],
            "storage_management": ["хранилище", "storage", "сохранить состояние", "экспортировать состояние", "save state", "export state"],
            "security_management": ["безопасность", "security", "секреты", "разблокировать", "secrets", "unlock"],
            "provider_setup": ["подключи провайдера", "подключи ИИ", "проверь подключение", "покажи провайдеры", "connect provider", "provider setup", "test connection", "show providers"],
        }

    def _extract_metadata(self, text: str) -> dict:
        metadata = {}
        decision_match = re.search(r"decision[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if decision_match:
            metadata["decisionId"] = decision_match.group(1)
        project_match = re.search(r"project[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if project_match:
            metadata["projectId"] = project_match.group(1)
        diff_match = re.search(r"diff[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if diff_match:
            metadata["diffPreviewId"] = diff_match.group(1)
        test_match = re.search(r"test(?:Plan)?[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if test_match:
            metadata["testPlanId"] = test_match.group(1)
        rollback_match = re.search(r"rollback[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if rollback_match:
            metadata["rollbackMetadataId"] = rollback_match.group(1)
        applyPackageId_match = re.search(r"apply(?:Package)?[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if applyPackageId_match:
            metadata["applyPackageId"] = applyPackageId_match.group(1)
        patchPlanResultId_match = re.search(r"patch(?:Plan)?[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if patchPlanResultId_match:
            metadata["patchPlanResultId"] = patchPlanResultId_match.group(1)
        workspaceId_match = re.search(r"workspace[:\s=]+([A-Za-z0-9_\-]+)", text or "", re.IGNORECASE)
        if workspaceId_match:
            metadata["workspaceId"] = workspaceId_match.group(1)
        return metadata

    def parse_message(self, session_id: str, message: DialogMessage) -> DialogCommand:
        raw_text = message.text or ""
        text = raw_text.lower().strip()
        metadata = self._extract_metadata(raw_text)
        ru_chars = sum(1 for c in raw_text if 'а' <= c.lower() <= 'я')
        en_chars = sum(1 for c in raw_text if 'a' <= c.lower() <= 'z')
        detected_language = "ru" if ru_chars > en_chars else "en"
        metadata["detectedLanguage"] = detected_language
        # Message metadata can explicitly supply projectId/promptId/decisionId.
        for key in ["projectId", "promptId", "decisionId", "diffPreviewId", "testPlanId", "rollbackMetadataId", "workspaceId", "patchPlanResultId", "applyPackageId", "commands", "targetFiles", "requestedChanges", "riskLevel", "title"]:
            if key in (message.metadata or {}):
                metadata[key] = message.metadata[key]
        for command_type, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern in text:
                    meta = {**metadata, "matchedPattern": pattern, "detectedLanguage": detected_language}
                    return DialogCommand(commandId=str(uuid.uuid4()), sessionId=session_id, messageId=message.messageId, commandType=command_type, inputText=raw_text, parsed=True, confidence=0.9, targetDecisionId=meta.get("decisionId"), targetApprovalPromptId=meta.get("promptId"), metadata=meta)
        if len(text) > 3:
            task = TaskRequest(input=raw_text, context={"sessionId": session_id}, requirements={}, metadata={"dialogSessionId": session_id, "dialogMessageId": message.messageId, "source": "dialog", **metadata})
            return DialogCommand(commandId=str(uuid.uuid4()), sessionId=session_id, messageId=message.messageId, commandType="resolve_task", inputText=raw_text, taskRequest=task, parsed=True, confidence=0.8, targetDecisionId=metadata.get("decisionId"), targetApprovalPromptId=metadata.get("promptId"), metadata=metadata)
        return DialogCommand(commandId=str(uuid.uuid4()), sessionId=session_id, messageId=message.messageId, commandType="unknown", inputText=raw_text, parsed=False, confidence=0.1, metadata=metadata)
