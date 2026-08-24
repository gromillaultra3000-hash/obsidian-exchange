from lumi.app.validation.unsafe_wording import UnsafeWordingDetector


def test_detect_forbidden_execution_english():
    assert UnsafeWordingDetector().detect_forbidden_execution_claim('I deployed to production without approval')


def test_detect_forbidden_execution_russian():
    assert UnsafeWordingDetector().detect_forbidden_execution_claim('я удалил файл')


def test_allow_permissive_context_english():
    assert UnsafeWordingDetector().detect_forbidden_execution_claim('I recommend deploying after approval') == []


def test_allow_permissive_context_russian():
    assert UnsafeWordingDetector().detect_forbidden_execution_claim('я предлагаю удалить после подтверждения') == []


def test_detect_secret_like_content():
    issues = UnsafeWordingDetector().detect_secret_like_content('Using api_key=sk-test-secret for access')
    assert issues and issues[0].code == 'SECRET_LIKE_CONTENT'


def test_no_false_positive_on_normal_text():
    assert UnsafeWordingDetector().detect_unsafe_wording('The system should be deployed after review') == []
