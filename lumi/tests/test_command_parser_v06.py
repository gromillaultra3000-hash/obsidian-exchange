from lumi.app.dialog.command_parser import CommandParser
from lumi.app.schemas.dialog import DialogMessage


def msg(text):
    return DialogMessage(messageId="m1", sessionId="s1", role="user", text=text)


def test_command_parser_core_commands():
    parser = CommandParser()
    assert parser.parse_message("s1", msg("объясни решение")).commandType == "explain_decision"
    assert parser.parse_message("s1", msg("покажи историю")).commandType == "show_history"
    assert parser.parse_message("s1", msg("статус")).commandType == "show_status"
    assert parser.parse_message("s1", msg("approve")).commandType == "approval_response"
    assert parser.parse_message("s1", msg("Analyze this code for vulnerabilities")).commandType == "resolve_task"
