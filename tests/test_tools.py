"""The tool registry: the one list of things Talk may do for a caller, and what must hold before it does any of them."""

import dataclasses

import pytest

from sofa.config import Settings
from sofa.orchestrator import understanding
from sofa.orchestrator.adapters.health import HealthAdapter
from sofa.orchestrator.wiring import Orchestrator, build_orchestrator, enabled_services
from sofa.orchestrator.tools import RISKS, Decision, Tool, ToolRegistry

HEALTH_TOOLS = {
    "health.find_facility", "health.facility_status", "health.available_slots", "health.book_appointment",
    "health.cancel_appointment", "health.drug_availability", "health.ask_the_centre",
}


@pytest.fixture
def tools():
    """The registry of a orchestrator with every service switched on, which is what a live line has."""
    return build_orchestrator().tools


@pytest.fixture
def booking_registry():
    """A small registry of its own, with one tool that cannot run until the caller has said which clinic and when."""
    registry = ToolRegistry()
    registry.register(Tool("clinic.book", "clinic", "Book an appointment at a clinic", risk="service", required=("facility", "when")))
    registry.register(Tool("clinic.opening_hours", "clinic", "Say when a clinic is open"))
    return registry


# ---- what is registered ------------------------------------------------------------------------------------------


def test_an_unregistered_operation_never_runs(tools):
    decision = tools.authorize("health.send_an_ambulance")
    assert not decision.allowed and decision.reason == "unregistered"


def test_an_unregistered_operation_is_refused_whatever_parameters_come_with_it(tools):
    decision = tools.authorize("health.send_an_ambulance", {"area": "Ikeja", "facility": "Ikeja Heights General Hospital"})
    assert decision == Decision(False, "unregistered")


def test_the_health_service_registers_exactly_the_operations_a_caller_can_ask_for(tools):
    assert {t.tool_id for t in tools.for_domain("health")} == HEALTH_TOOLS


def test_every_registered_operation_has_one_of_the_known_risks(tools):
    assert RISKS == ("informational", "service")
    for domain in ("health",):
        for tool in tools.for_domain(domain):
            assert tool.risk in RISKS, tool.tool_id


def test_every_registered_operation_is_named_as_a_service_dot_operation(tools):
    for domain in ("health",):
        for tool in tools.for_domain(domain):
            assert tool.tool_id.startswith(f"{domain}.") and tool.description.strip(), tool.tool_id


def test_a_domain_with_no_tools_lists_nothing_and_an_unknown_tool_is_not_found(tools):
    assert tools.for_domain("dentistry") == []
    assert tools.get("health.not_a_real_operation") is None
    assert tools.get("health.find_facility").domain == "health"


def test_the_tools_of_one_domain_never_include_those_of_another(tools):
    assert not {t.tool_id for t in tools.for_domain("dentistry")} & HEALTH_TOOLS
    assert {t.domain for t in tools.for_domain("health")} == {"health"}


# ---- who may run what --------------------------------------------------------------------------------------------


def test_a_registered_operation_that_needs_nothing_more_is_allowed(tools):
    for tool_id in sorted(HEALTH_TOOLS):
        decision = tools.authorize(tool_id)
        assert decision.allowed and decision.reason == "", tool_id


def test_an_operation_waits_until_the_first_missing_parameter_is_given(booking_registry):
    decision = booking_registry.authorize("clinic.book")
    assert not decision.allowed and decision.reason == "missing:facility"
    decision = booking_registry.authorize("clinic.book", {"facility": "Surulere Care Clinic"})
    assert not decision.allowed and decision.reason == "missing:when"


def test_an_operation_with_every_parameter_is_allowed(booking_registry):
    decision = booking_registry.authorize("clinic.book", {"facility": "Surulere Care Clinic", "when": "tomorrow morning"})
    assert decision.allowed and decision.reason == ""


def test_a_parameter_that_is_empty_counts_as_missing(booking_registry):
    assert booking_registry.authorize("clinic.book", {"facility": "", "when": "tomorrow morning"}).reason == "missing:facility"
    assert booking_registry.authorize("clinic.book", {"facility": "Surulere Care Clinic", "when": None}).reason == "missing:when"


def test_missing_parameters_are_reported_when_no_parameters_are_passed_at_all(booking_registry):
    assert booking_registry.authorize("clinic.book", None).reason == "missing:facility"
    assert booking_registry.authorize("clinic.book", {}).reason == "missing:facility"


def test_parameters_that_are_not_required_are_ignored(booking_registry):
    assert booking_registry.authorize("clinic.opening_hours").allowed
    assert booking_registry.authorize("clinic.opening_hours", {"anything": "at all"}).allowed
    assert booking_registry.authorize("clinic.book", {"facility": "Aguda", "when": "Friday", "extra": 1}).allowed


def test_an_unregistered_operation_is_refused_before_any_parameter_is_looked_at(booking_registry):
    assert booking_registry.authorize("clinic.teleport", {"facility": "Aguda", "when": "Friday"}).reason == "unregistered"


def test_a_decision_cannot_be_changed_once_it_is_made():
    decision = Decision(True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.allowed = False


def test_the_orchestrator_asks_the_registry_whether_an_operation_may_run():
    orchestrator = build_orchestrator()
    assert orchestrator.authorize("health.book_appointment").allowed
    assert orchestrator.authorize("health.send_an_ambulance").reason == "unregistered"


# ---- registering ------------------------------------------------------------------------------------------------


def test_a_tool_cannot_be_registered_twice():
    registry = ToolRegistry()
    registry.register(Tool("clinic.opening_hours", "clinic", "Say when a clinic is open"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("clinic.opening_hours", "clinic", "The same operation again"))


def test_two_services_cannot_claim_the_same_operation():
    with pytest.raises(ValueError, match="already registered"):
        Orchestrator([HealthAdapter(), HealthAdapter()])


def test_a_tool_id_without_an_operation_is_refused():
    with pytest.raises(ValueError, match="service.operation"):
        Tool("opening_hours", "clinic", "There is no service in front of the operation")


def test_a_tool_with_an_unknown_risk_is_refused():
    with pytest.raises(ValueError, match="unknown risk"):
        Tool("clinic.opening_hours", "clinic", "Say when a clinic is open", risk="spicy")


def test_a_registered_tool_is_not_changed_by_anyone_afterwards():
    tool = Tool("clinic.opening_hours", "clinic", "Say when a clinic is open")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tool.risk = "service"


def test_a_tool_is_informational_and_needs_nothing_unless_it_says_otherwise():
    tool = Tool("clinic.opening_hours", "clinic", "Say when a clinic is open")
    assert tool.risk == "informational" and tool.required == ()


# ---- which services are switched on -------------------------------------------------------------------------------


def test_every_service_is_switched_on_when_no_settings_are_given():
    assert enabled_services() == ["health"]
    assert build_orchestrator().domains() == ["health"]


def test_spaces_around_a_service_name_are_ignored():
    assert enabled_services(Settings(services_enabled=" health ", _env_file=None)) == ["health"]


def test_a_service_name_that_does_not_exist_is_ignored():
    assert enabled_services(Settings(services_enabled="health,dentistry", _env_file=None)) == ["health"]


def test_a_service_that_is_switched_off_has_no_tools():
    orchestrator = build_orchestrator(Settings(services_enabled="none", _env_file=None))
    assert orchestrator.domains() == [] and orchestrator.adapter("health") is None
    assert orchestrator.tools.for_domain("health") == []
    assert orchestrator.authorize("health.find_facility").reason == "unregistered"


def test_only_the_health_operations_can_be_named_as_the_callers_action():
    voice = build_orchestrator().voice_tools()
    assert set(voice) == HEALTH_TOOLS and set(voice.values()) == {"health"}


def test_a_service_switched_off_offers_the_model_nothing_to_name():
    orchestrator = build_orchestrator(Settings(services_enabled="none", _env_file=None))
    assert orchestrator.voice_tools() == {} and orchestrator.extra_domains() == []


# ---- what the model may name -------------------------------------------------------------------------------------


def test_the_answer_format_lists_every_registered_operation_and_the_fixed_choices():
    voice = build_orchestrator().voice_tools()
    wire = understanding.schema(list(voice), ["health"])
    actions = wire["properties"]["action"]["enum"]
    assert set(actions) == HEALTH_TOOLS | {"chat", "human", "unclear", "health"}


def test_every_field_in_the_answer_format_is_required_and_nothing_extra_is_allowed():
    wire = understanding.schema(sorted(HEALTH_TOOLS), ["health"])
    assert set(wire["required"]) == set(wire["properties"]) == {"urgency", "action", "answer"}
    assert wire["properties"]["urgency"]["enum"] == ["none", "possible", "emergency"]
    assert wire["additionalProperties"] is False
    assert wire["properties"]["answer"]["enum"] == ["yes", "no", "none"]


def test_an_operation_the_model_invents_is_treated_as_not_understood():
    heard = understanding.Understanding(action="health.send_an_ambulance", answer="none")
    heard.settle(build_orchestrator().voice_tools(), ["health"])
    assert heard.action == "unclear" and heard.domain == "unclear" and heard.tool is None


def test_an_operation_that_is_registered_keeps_its_service_and_its_name():
    heard = understanding.Understanding(action="health.book_appointment", answer="none")
    heard.settle(build_orchestrator().voice_tools(), ["health"])
    assert heard.domain == "health" and heard.tool == "health.book_appointment" and heard.action == "health.book_appointment"


def test_a_fixed_choice_is_understood_without_a_tool():
    for choice in ("chat", "human", "unclear"):
        heard = understanding.Understanding(action=choice)
        assert heard.domain == choice and heard.tool is None, choice


def test_the_name_of_a_service_that_is_not_registered_is_not_understood():
    heard = understanding.Understanding(action="dentistry")
    heard.settle({}, [])
    assert heard.domain == "unclear" and heard.tool is None


def test_an_answer_the_model_writes_as_none_or_nothing_means_no_answer_was_given():
    assert understanding.Understanding(action="unclear", answer="none").answer is None
    assert understanding.Understanding(action="unclear", answer="").answer is None
    assert understanding.Understanding(action="unclear", answer="yes").answer == "yes"
