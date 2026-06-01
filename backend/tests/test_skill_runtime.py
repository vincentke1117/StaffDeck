from app.core.skill_runtime import SkillRuntime
from app.db.models import ChatSession
from app.session.session_schema import RouterDecision


def test_suspend_and_explicitly_restore_skill_stack():
    session = ChatSession(
        id="session_test",
        tenant_id="tenant_demo",
        active_skill_id="repair_ticket",
        active_step_id="collect_repair_info",
        slots_json={"asset_id": "EQ-9"},
    )
    runtime = SkillRuntime()

    runtime.apply_decision(
        session,
        RouterDecision(
            decision="suspend_current_and_start_new_skill",
            target_skill_id="visitor_badge",
            target_step_id="collect_visit_info",
        ),
    )

    assert session.active_skill_id == "visitor_badge"
    assert session.active_step_id == "collect_visit_info"
    assert session.slots_json == {}
    assert session.skill_stack_json[0]["skill_id"] == "repair_ticket"

    runtime.apply_decision(
        session,
        RouterDecision(
            decision="suspend_current_and_start_new_skill",
            target_skill_id="repair_ticket",
            target_step_id="collect_repair_info",
        ),
    )

    assert session.active_skill_id == "repair_ticket"
    assert session.active_step_id == "collect_repair_info"
    assert session.slots_json == {"asset_id": "EQ-9"}
    assert session.skill_stack_json[0]["skill_id"] == "visitor_badge"


def test_exit_current_skill_does_not_auto_resume_suspended_skill():
    session = ChatSession(
        id="session_test",
        tenant_id="tenant_demo",
        active_skill_id="repair_ticket",
        active_step_id="collect_repair_info",
        skill_stack_json=[
            {
                "skill_id": "visitor_badge",
                "step_id": "collect_visit_info",
                "slots": {"visitor_name": "hm"},
            }
        ],
    )
    runtime = SkillRuntime()

    runtime.apply_decision(session, RouterDecision(decision="exit_current_skill"))

    assert session.active_skill_id is None
    assert session.active_step_id is None
    assert session.slots_json == {}
    assert session.skill_stack_json[0]["skill_id"] == "visitor_badge"


def test_start_skill_removes_stale_same_skill_stack_frames():
    session = ChatSession(
        id="session_test",
        tenant_id="tenant_demo",
        active_skill_id="repair_ticket",
        active_step_id="collect_repair_info",
        skill_stack_json=[
            {
                "skill_id": "visitor_badge",
                "step_id": "collect_visit_info",
                "slots": {"visitor_name": "hm"},
            },
            {
                "skill_id": "repair_ticket",
                "step_id": "collect_repair_info",
                "slots": {"asset_id": "EQ-9"},
            },
        ],
    )
    runtime = SkillRuntime()

    runtime.apply_decision(
        session,
        RouterDecision(
            decision="start_skill",
            target_skill_id="repair_ticket",
            target_step_id="collect_repair_info",
        ),
    )

    assert session.active_skill_id == "repair_ticket"
    assert session.active_step_id == "collect_repair_info"
    assert session.slots_json == {}
    assert session.skill_stack_json == [
        {
            "skill_id": "visitor_badge",
            "step_id": "collect_visit_info",
            "slots": {"visitor_name": "hm"},
        }
    ]


def test_related_question_restores_after_answer():
    session = ChatSession(
        id="session_test",
        tenant_id="tenant_demo",
        active_skill_id="repair_ticket",
        active_step_id="collect_repair_info",
    )
    runtime = SkillRuntime()

    runtime.apply_decision(
        session,
        RouterDecision(
            decision="answer_related_question_then_resume",
            target_skill_id="repair_ticket",
            target_step_id="answer_warranty_policy",
            should_resume_after_answer=True,
        ),
    )
    assert session.active_step_id == "answer_warranty_policy"
    assert session.resume_after_answer_json == {
        "skill_id": "repair_ticket",
        "step_id": "collect_repair_info",
        "slots": {},
        "summary": None,
        "last_agent_question": None,
    }

    runtime.finish_interrupt_response(session)

    assert session.active_step_id == "collect_repair_info"
    assert session.resume_after_answer_json is None


def test_related_question_to_another_skill_suspends_and_restores_original_context():
    session = ChatSession(
        id="session_test",
        tenant_id="tenant_demo",
        active_skill_id="purchase",
        active_step_id="collect_user_name",
        slots_json={"product_id": "A1"},
        summary="最近回复：请问姓名和数量",
        last_agent_question="请问姓名和数量？",
    )
    runtime = SkillRuntime()

    runtime.apply_decision(
        session,
        RouterDecision(
            decision="answer_related_question_then_resume",
            target_skill_id="price_compare",
            target_step_id="collect_products",
            should_resume_after_answer=True,
        ),
    )

    assert session.active_skill_id == "price_compare"
    assert session.active_step_id == "collect_products"
    assert session.slots_json == {}
    assert session.skill_stack_json == [
        {
            "skill_id": "purchase",
            "step_id": "collect_user_name",
            "slots": {"product_id": "A1"},
            "summary": "最近回复：请问姓名和数量",
            "last_agent_question": "请问姓名和数量？",
        }
    ]
    assert session.resume_after_answer_json == session.skill_stack_json[0]

    session.slots_json = {"product_name_1": "A1", "product_name_2": "A3"}
    runtime.finish_interrupt_response(session)

    assert session.active_skill_id == "purchase"
    assert session.active_step_id == "collect_user_name"
    assert session.slots_json == {"product_id": "A1"}
    assert session.skill_stack_json == []
    assert session.resume_after_answer_json is None
