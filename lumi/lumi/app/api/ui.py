from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response
from lumi.app.core.runtime import runtime_instance
from lumi.app.ui.ui_helpers import UiHelpers

router = APIRouter(tags=["ui"])
helpers = UiHelpers(runtime_instance.redaction)

@router.get("/ui", response_class=HTMLResponse)
async def ui_dashboard():
    content = helpers.read_static_file("index.html")
    if content is None:
        return HTMLResponse("<h1>Lumi Dashboard not found</h1>", status_code=404)
    if runtime_instance.audit_log:
        runtime_instance.audit_log.add_entry("ui_dashboard_opened", summary="UI dashboard opened")
    return HTMLResponse(content)

@router.get("/ui/", response_class=HTMLResponse)
async def ui_dashboard_slash():
    return await ui_dashboard()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return await ui_dashboard()

@router.get("/ui/app.js")
async def ui_app_js():
    content = helpers.read_static_file("app.js")
    if content is None:
        return JSONResponse({"error": "app.js not found"}, status_code=404)
    return Response(content=content, media_type="application/javascript")

@router.get("/ui/styles.css")
async def ui_styles_css():
    content = helpers.read_static_file("styles.css")
    if content is None:
        return JSONResponse({"error": "styles.css not found"}, status_code=404)
    return Response(content=content, media_type="text/css")

@router.get("/ui/components/{component_name}.js")
async def ui_component_js(component_name: str):
    if ".." in component_name or "/" in component_name or "\\" in component_name:
        return JSONResponse({"error": "Invalid component name"}, status_code=400)
    content = helpers.read_static_file(f"components/{component_name}.js")
    if content is None:
        return JSONResponse({"error": f"Component {component_name}.js not found"}, status_code=404)
    return Response(content=content, media_type="application/javascript")

@router.get("/ui/state")
async def ui_state():
    return runtime_instance.get_ui_dashboard_summary()

@router.get("/dashboard/state")
async def dashboard_state():
    return runtime_instance.get_ui_dashboard_summary()

@router.get("/ui/panels")
async def ui_panels():
    if runtime_instance.audit_log:
        runtime_instance.audit_log.add_entry("ui_panel_requested", summary="UI panels requested")
    return runtime_instance.get_ui_panel_configs()

@router.get("/ui/safety-labels")
async def ui_safety_labels():
    return runtime_instance.get_ui_safety_labels()

@router.get("/ui/wizards/integration")
async def ui_wizard_integration():
    if runtime_instance.audit_log:
        runtime_instance.audit_log.add_entry("ui_wizard_state_requested", summary="Integration wizard state requested")
    return runtime_instance.get_integration_wizard_state()

@router.get("/ui/wizards/project")
async def ui_wizard_project():
    if runtime_instance.audit_log:
        runtime_instance.audit_log.add_entry("ui_wizard_state_requested", summary="Project wizard state requested")
    return runtime_instance.get_project_wizard_state()
