from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from skillify.index.db import init_db, make_engine
from skillify.index.models import WorkPackageRecord
from skillify.tasks.work_package import WorkPackage, validate_delegation_result


def package(identifier="wp-1", dependencies=None):
    return WorkPackage.from_dict({
        "packageId": identifier, "taskId": "task-1", "objective": "Change parser module",
        "allowedPaths": ["src/parser/**"], "dependencies": dependencies or [], "access": "write",
        "recommendedSkills": ["test-driven-development"], "recommendedMcp": ["codegraph"],
        "acceptanceCommands": ["pytest tests/test_parser.py"], "parallelizable": True,
    })


def test_work_package_validates_context_and_result_boundaries() -> None:
    first = package()
    second = package("wp-2", ["wp-1"])
    validate_delegation_result("adaptive", (first,))
    validate_delegation_result("suggested", (first, second))
    validate_delegation_result("required", (first, second))
    with pytest.raises(ValueError, match="at least two"):
        validate_delegation_result("required", (first,))
    with pytest.raises(ValueError, match="relative"):
        WorkPackage.from_dict({**first.to_dict(), "allowedPaths": ["../secret"]})


def test_work_package_record_is_available_in_sqlite(tmp_path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'packages.db'}")
    init_db(engine)
    item = package()
    with Session(engine) as session:
        session.add(WorkPackageRecord(
            package_id=item.package_id, task_id=item.task_id, objective=item.objective,
            allowed_paths=list(item.allowed_paths), dependencies=list(item.dependencies),
            access=item.access, recommended_skills=list(item.recommended_skills),
            recommended_mcp=list(item.recommended_mcp),
            acceptance_commands=list(item.acceptance_commands),
            parallelizable=item.parallelizable, confirmed=item.confirmed,
        ))
        session.commit()
        assert session.query(WorkPackageRecord).one().objective == item.objective
