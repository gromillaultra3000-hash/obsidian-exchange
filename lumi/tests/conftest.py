import pytest
from lumi.app.core.runtime import runtime_instance

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()
