from src.agent.orchestrator import orchestrate


def test_orchestrator_returns_message() -> None:
    result = orchestrate("hola")
    assert "hola" in result
