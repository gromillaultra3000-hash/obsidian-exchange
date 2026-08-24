from typing import Optional, List
from lumi.app.schemas.sandbox import SandboxTestRunResult, ApplyPreparationPackage

class SandboxResultStore:
    def __init__(self):
        self._test_results: dict[str, SandboxTestRunResult] = {}
        self._apply_packages: dict[str, ApplyPreparationPackage] = {}
    def add_test_result(self, result: SandboxTestRunResult) -> SandboxTestRunResult:
        self._test_results[result.testRunResultId] = result
        return result
    def get_test_result(self, test_run_result_id: str) -> Optional[SandboxTestRunResult]:
        return self._test_results.get(test_run_result_id)
    def list_test_results(self, project_id: Optional[str] = None) -> List[SandboxTestRunResult]:
        vals = list(self._test_results.values())
        return [r for r in vals if r.projectId == project_id] if project_id else vals
    def add_apply_package(self, package: ApplyPreparationPackage) -> ApplyPreparationPackage:
        self._apply_packages[package.applyPackageId] = package
        return package
    def get_apply_package(self, apply_package_id: str) -> Optional[ApplyPreparationPackage]:
        return self._apply_packages.get(apply_package_id)
    def list_apply_packages(self, project_id: Optional[str] = None) -> List[ApplyPreparationPackage]:
        vals = list(self._apply_packages.values())
        return [p for p in vals if p.projectId == project_id] if project_id else vals
    def clear_for_tests(self):
        self._test_results.clear(); self._apply_packages.clear()
