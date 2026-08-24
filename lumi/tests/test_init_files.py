import os
import importlib
import sys


def test_no_init_py_files():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for root, dirs, files in os.walk(project_root):
        for file in files:
            assert file != "init.py", f"Found forbidden file init.py at {os.path.join(root, file)}"


def test_required_init_py_exist():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    required_dirs = [
        "lumi/app", "lumi/app/version", "lumi/app/core", "lumi/app/schemas", "lumi/app/providers", "lumi/app/resolver", "lumi/app/audit", "lumi/app/api", "lumi/app/capabilities", "lumi/app/roles", "lumi/app/routing", "lumi/app/validation", "lumi/app/conflict", "lumi/app/policy", "lumi/app/actions", "lumi/app/history", "lumi/app/explainability", "lumi/app/dialog",
        "lumi/app/integration", "lumi/app/project_scanner", "lumi/app/patch_planner", "lumi/app/sandbox", "lumi/app/ui", "tests", "sdk/python/lumi_client",
    ]
    for rel_dir in required_dirs:
        init_file = os.path.join(project_root, rel_dir, "__init__.py")
        assert os.path.exists(init_file), f"Missing __init__.py in {rel_dir}"


def test_key_modules_import():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sdk_path = os.path.join(project_root, "sdk", "python")
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    modules = [
        "lumi.app.main", "lumi.app.core.runtime", "lumi.app.providers.registry", "lumi.app.resolver.basic_resolver", "lumi.app.resolver.routing_resolver", "lumi.app.resolver.validated_routing_resolver", "lumi.app.capabilities.capability_catalog", "lumi.app.capabilities.capability_profile", "lumi.app.capabilities.capability_matcher", "lumi.app.roles.role_catalog", "lumi.app.roles.role_assignment", "lumi.app.roles.role_matcher", "lumi.app.routing.task_classifier", "lumi.app.routing.task_requirements", "lumi.app.routing.route_plan", "lumi.app.routing.provider_router", "lumi.app.validation.output_normalizer", "lumi.app.validation.output_validator", "lumi.app.validation.validation_rules", "lumi.app.validation.validation_score", "lumi.app.validation.validation_pipeline", "lumi.app.validation.unsafe_wording", "lumi.app.conflict.conflict_detector", "lumi.app.conflict.deterministic_resolver", "lumi.app.policy.policy_registry", "lumi.app.policy.policy_engine", "lumi.app.policy.policy_defaults", "lumi.app.policy.limits", "lumi.app.policy.policy_check", "lumi.app.actions.action_registry", "lumi.app.actions.action_gateway", "lumi.app.actions.action_proposal", "lumi.app.actions.approval_prompt", "lumi.app.actions.action_risk", "lumi.app.history.decision_history", "lumi.app.history.decision_index", "lumi.app.history.decision_filters", "lumi.app.history.timeline_builder", "lumi.app.explainability.explanation_builder", "lumi.app.explainability.human_summary", "lumi.app.explainability.technical_summary", "lumi.app.explainability.explanation_templates", "lumi.app.dialog.dialog_session", "lumi.app.dialog.dialog_message", "lumi.app.dialog.dialog_runtime", "lumi.app.dialog.command_parser", "lumi.app.dialog.response_builder",
        "lumi.app.integration.host_app_registry",
        "lumi.app.integration.host_manifest",
        "lumi.app.integration.integration_handshake",
        "lumi.app.integration.connector_contract",
        "lumi.app.integration.event_contract",
        "lumi.app.integration.callback_contract",
        "lumi.app.integration.sidecar_runtime",
        "lumi.app.project_scanner.project_registry",
        "lumi.app.project_scanner.project_manifest",
        "lumi.app.project_scanner.file_snapshot_store",
        "lumi.app.project_scanner.inventory_builder",
        "lumi.app.project_scanner.static_inspector",
        "lumi.app.project_scanner.issue_detector",
        "lumi.app.project_scanner.improvement_candidate",
        "lumi.app.project_scanner.improvement_planner",
        "lumi.app.project_scanner.patch_plan_preview",
        "lumi.app.project_scanner.scan_runtime",

        "lumi.app.patch_planner.patch_request",
        "lumi.app.patch_planner.patch_safety",
        "lumi.app.patch_planner.patch_proposal",
        "lumi.app.patch_planner.diff_preview",
        "lumi.app.patch_planner.test_plan",
        "lumi.app.patch_planner.test_runner_preview",
        "lumi.app.patch_planner.rollback_metadata",
        "lumi.app.patch_planner.patch_runtime",
        "lumi.app.sandbox.sandbox_workspace",
        "lumi.app.sandbox.sandbox_store",
        "lumi.app.sandbox.sandbox_patch_applier",
        "lumi.app.sandbox.command_guard",
        "lumi.app.sandbox.sandbox_test_runner",
        "lumi.app.sandbox.sandbox_result_store",
        "lumi.app.sandbox.apply_preparation",
        "lumi.app.sandbox.apply_package",
        "lumi.app.sandbox.sandbox_runtime",
        "lumi.app.ui.ui_state",
        "lumi.app.ui.ui_schemas",
        "lumi.app.ui.ui_helpers",
        "lumi.app.ui.ui_routes",
        "lumi_client.client",
    ]
    for mod_name in modules:
        importlib.import_module(mod_name)


def test_compileall():
    import py_compile
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors = []
    for root, dirs, files in os.walk(project_root):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(str(exc))
    assert not errors, f"Compile errors: {errors}"
