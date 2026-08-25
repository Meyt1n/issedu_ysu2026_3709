"""HCT-439 阶段五：演示数据清理脚本的安全边界。

脚本只允许清理带显式 demo-/test- 标记的家庭；默认 dry-run 不改数据，
--apply 时通过 HCT-405 擦除服务传播删除，真实家庭必须原样保留。
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Household, Member
from cleanup_demo_data import (
    cleanup_demo_households,
    find_demo_households,
    is_demo_household,
)


@pytest.fixture()
def isolated_file_root(tmp_path) -> Generator[None, None, None]:
    settings = get_settings()
    previous = settings.file_root
    settings.file_root = str(tmp_path / "files")
    try:
        yield
    finally:
        settings.file_root = previous


def _household(session: Session, name: str, created_by: str) -> Household:
    household = Household(name=name, created_by=created_by)
    session.add(household)
    session.flush()
    session.add(
        Member(
            household_id=household.id,
            display_name=f"{name}成员",
            role="DEPENDENT",
        )
    )
    session.flush()
    return household


def test_only_explicitly_marked_households_are_selected(db_session: Session) -> None:
    demo_by_actor = _household(db_session, "爷爷奶奶家", "demo-parent")
    demo_by_name = _household(db_session, "test-家庭", "parent-2")
    demo_by_marker = _household(db_session, "爷爷奶奶家（本地演示）", "parent-3")
    real = _household(db_session, "真实家庭", "parent-1")
    # demo/test 出现在中间不算显式标记，避免误删真实家庭。
    fuzzy = _household(db_session, "小test家", "my-demo-account")

    assert is_demo_household(demo_by_actor)
    assert is_demo_household(demo_by_name)
    assert is_demo_household(demo_by_marker)
    assert not is_demo_household(real)
    assert not is_demo_household(fuzzy)

    selected = {household.id for household in find_demo_households(db_session)}
    assert selected == {demo_by_actor.id, demo_by_name.id, demo_by_marker.id}


def test_dry_run_reports_plan_without_changing_data(db_session: Session) -> None:
    demo = _household(db_session, "爷爷奶奶家", "demo-parent")
    real = _household(db_session, "真实家庭", "parent-1")

    report = cleanup_demo_households(db_session, apply=False)

    assert report["dry_run"] is True
    assert report["matched"] == 1
    assert report["plan"][0]["household_id"] == demo.id
    assert report["results"] == []
    db_session.expire_all()
    assert db_session.get(Household, demo.id).deleted_at is None
    assert db_session.get(Household, real.id).deleted_at is None


def test_apply_erases_demo_households_and_keeps_real_data(
    db_session: Session,
    isolated_file_root: None,
) -> None:
    demo = _household(db_session, "爷爷奶奶家（本地演示）", "demo-parent")
    real = _household(db_session, "真实家庭", "parent-1")

    report = cleanup_demo_households(db_session, apply=True)

    assert report["dry_run"] is False
    assert report["matched"] == 1
    assert report["results"][0]["household_id"] == demo.id
    assert report["results"][0]["erasure_status"] == "completed"
    db_session.expire_all()
    assert db_session.get(Household, demo.id).deleted_at is not None
    assert db_session.get(Household, real.id).deleted_at is None
    real_members = [
        member
        for member in db_session.query(Member).filter(Member.household_id == real.id).all()
        if member.deleted_at is None
    ]
    assert len(real_members) == 1
