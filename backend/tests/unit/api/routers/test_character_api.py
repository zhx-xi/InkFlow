"""F9 角色管理 API 测试 — Mock Service 层（M5 RED→GREEN）.

测试范围 (spec §9 API 测试 + §3.5 异常映射表):
- 16 端点成功路径（201/200/204）
- 404 全路径（项目/角色/分组/关系不存在、无效 UUID）
- 422 业务校验（同名/自环/重复关系/跨项目/group 跨项目）
- extract 200 / extract LLM 失败 → 500 / 解析失败 → 500
- 角色详情含 relations 聚合（spec §3.4）
- 分页参数校验（limit 越界 → 422）

策略: @patch("inkflow.api.routers.characters.get_character_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f9-character-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers.characters import (
    CharacterGroupUpdateBody,
    CharacterRelationUpdateBody,
    _validate_group_name,
)
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterGroup,
    CharacterRelation,
)
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    CharacterNameConflictError,
    CharacterNotFoundError,
    CrossProjectRelationError,
    GroupNameConflictError,
    GroupNotInProjectError,
    ProjectNotFoundError,
    RelationConflictError,
    SelfRelationError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _char(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    group_ids: list[uuid.UUID] | None = None,
) -> Character:
    """构造测试用角色实体（固定时间戳，便于断言）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        personality="坚韧隐忍",
        background="废柴体质觉醒者",
        goals="成为强者",
        group_ids=group_ids or [],
        created_at=TS,
        updated_at=TS,
    )


def _group(name: str, *, project_id: uuid.UUID = PID) -> CharacterGroup:
    """构造测试用分组实体。"""
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description="主角团",
        sort_order=1,
        created_at=TS,
        updated_at=TS,
    )


def _rel(
    from_char: Character,
    to_char: Character,
    *,
    relation_type: str,
    description: str = "",
) -> CharacterRelation:
    """构造测试用关系实体。"""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=from_char.project_id,
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=relation_type,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock CharacterService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestCharacterCRUDAPI:
    """角色 CRUD 端点测试."""

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_character_success(self, mock_get_svc: MagicMock) -> None:
        """创建角色返回 201 + Character JSON."""
        svc = _mock_svc(mock_get_svc)
        char = _char("林尘")
        svc.create_character = AsyncMock(return_value=char)

        g1, g2 = uuid.uuid4(), uuid.uuid4()
        response = client.post(
            f"/api/v1/projects/{PID}/characters",
            json={
                "name": "林尘",
                "personality": "坚韧隐忍",
                "group_ids": [str(g1), str(g2)],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "林尘"
        assert data["personality"] == "坚韧隐忍"
        assert data["project_id"] == str(PID)
        svc.create_character.assert_awaited_once_with(
            PID, "林尘", "坚韧隐忍", "", "", [g1, g2], extra={}
        )

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_character_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动角色创建返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_character = AsyncMock(side_effect=CharacterNameConflictError())

        response = client.post(f"/api/v1/projects/{PID}/characters", json={"name": "林尘"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名角色已存在（角色名在项目内必须唯一）"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_character_group_not_in_project_422(self, mock_get_svc: MagicMock) -> None:
        """分组不存在/不属于该项目返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_character = AsyncMock(side_effect=GroupNotInProjectError())

        response = client.post(
            f"/api/v1/projects/{PID}/characters",
            json={"name": "林尘", "group_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "分组不存在于该项目"

    def test_create_character_missing_name_422(self) -> None:
        """缺少必填字段 name 返回 422（Pydantic 校验）."""
        response = client.post(f"/api/v1/projects/{PID}/characters", json={"personality": "x"})
        assert response.status_code == 422

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_list_characters_success(self, mock_get_svc: MagicMock) -> None:
        """角色列表返回 200 + {items, total, offset, limit}."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        char = _char("林尘", group_ids=[group.id])
        svc.list_characters = AsyncMock(return_value=([char], 1))
        svc.list_groups = AsyncMock(return_value=[group])

        gid = uuid.uuid4()
        response = client.get(
            f"/api/v1/projects/{PID}/characters",
            params={
                "search": "林",
                "group_id": str(gid),
                "sort_by": "name",
                "sort_desc": "false",
                "offset": 0,
                "limit": 20,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 20
        assert data["items"][0]["name"] == "林尘"
        assert data["items"][0]["group_ids"] == [str(group.id)]
        assert data["items"][0]["group_names"] == ["主角团"]
        svc.list_characters.assert_awaited_once_with(
            PID,
            search="林",
            group_id=gid,
            sort_by="name",
            sort_desc=False,
            offset=0,
            limit=20,
        )

    def test_list_characters_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0）返回 422."""
        response = client.get(f"/api/v1/projects/{PID}/characters", params={"limit": 0})
        assert response.status_code == 422

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_get_character_success_with_relations(self, mock_get_svc: MagicMock) -> None:
        """角色详情返回 200，含 relations 双向聚合（spec §3.4）."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        char = _char("林尘", group_ids=[group.id])
        other = _char("青云真人")
        rel = _rel(char, other, relation_type="师徒", description="关门弟子")
        svc.get_character = AsyncMock(side_effect=[char, other])
        svc.list_relations = AsyncMock(return_value=[rel])
        svc.list_groups = AsyncMock(return_value=[group])

        response = client.get(f"/api/v1/characters/{char.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "林尘"
        assert data["group_ids"] == [str(group.id)]
        assert data["group_names"] == ["主角团"]
        assert len(data["relations"]) == 1
        item = data["relations"][0]
        assert item["to_character_id"] == str(other.id)
        assert item["to_name"] == "青云真人"
        assert item["relation_type"] == "师徒"
        assert "from_character_id" not in item

    def test_get_character_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404."""
        response = client.get("/api/v1/characters/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_get_character_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """角色不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_character = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/characters/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_character_success(self, mock_get_svc: MagicMock) -> None:
        """更新角色返回 200 + Character JSON."""
        svc = _mock_svc(mock_get_svc)
        char = _char("林尘")
        g1, g2 = uuid.uuid4(), uuid.uuid4()
        updated = char.model_copy(update={"goals": "成为青云宗首席弟子", "group_ids": [g1, g2]})
        svc.update_character = AsyncMock(return_value=updated)

        response = client.patch(
            f"/api/v1/characters/{char.id}",
            json={"goals": "成为青云宗首席弟子", "group_ids": [str(g1), str(g2)]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["goals"] == "成为青云宗首席弟子"
        assert data["group_ids"] == [str(g1), str(g2)]
        update = svc.update_character.await_args.args[1]
        assert update.group_ids == [g1, g2]
        assert "group_ids" in update.model_fields_set

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_character_204(self, mock_get_svc: MagicMock) -> None:
        """删除角色返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_character = AsyncMock(return_value=True)

        char_id = uuid.uuid4()
        response = client.delete(f"/api/v1/characters/{char_id}")
        assert response.status_code == 204
        svc.delete_character.assert_awaited_once_with(char_id)

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_character_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的角色返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_character = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/characters/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"


class TestRelationAPI:
    """角色关系端点测试."""

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_relation_success(self, mock_get_svc: MagicMock) -> None:
        """创建关系返回 201 + CharacterRelation JSON."""
        svc = _mock_svc(mock_get_svc)
        char = _char("林尘")
        other = _char("青云真人")
        rel = _rel(char, other, relation_type="师徒", description="关门弟子")
        svc.create_relation = AsyncMock(return_value=rel)

        response = client.post(
            f"/api/v1/characters/{char.id}/relations",
            json={
                "to_character_id": str(other.id),
                "relation_type": "师徒",
                "description": "关门弟子",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["relation_type"] == "师徒"
        assert data["from_character_id"] == str(char.id)
        svc.create_relation.assert_awaited_once_with(char.id, other.id, "师徒", "关门弟子")

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_relation_self_422(self, mock_get_svc: MagicMock) -> None:
        """关系两端同一角色（自环）返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=SelfRelationError())

        response = client.post(
            f"/api/v1/characters/{uuid.uuid4()}/relations",
            json={"to_character_id": str(uuid.uuid4()), "relation_type": "师徒"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "关系两端不能是同一角色"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_relation_duplicate_422(self, mock_get_svc: MagicMock) -> None:
        """重复创建相同活动关系返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=RelationConflictError())

        response = client.post(
            f"/api/v1/characters/{uuid.uuid4()}/relations",
            json={"to_character_id": str(uuid.uuid4()), "relation_type": "师徒"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "该关系已存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_relation_cross_project_422(self, mock_get_svc: MagicMock) -> None:
        """关系两端角色跨项目返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=CrossProjectRelationError())

        response = client.post(
            f"/api/v1/characters/{uuid.uuid4()}/relations",
            json={"to_character_id": str(uuid.uuid4()), "relation_type": "师徒"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "角色与目标角色不属于同一项目"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_relation_to_character_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """关系目标角色不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=CharacterNotFoundError())

        response = client.post(
            f"/api/v1/characters/{uuid.uuid4()}/relations",
            json={"to_character_id": str(uuid.uuid4()), "relation_type": "师徒"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_list_relations_success(self, mock_get_svc: MagicMock) -> None:
        """关系列表返回 200，聚合 from_name/to_name（spec §3.3）."""
        svc = _mock_svc(mock_get_svc)
        char = _char("林尘")
        other = _char("青云真人")
        rel = _rel(char, other, relation_type="师徒", description="关门弟子")
        svc.list_relations = AsyncMock(return_value=[rel])
        svc.get_character = AsyncMock(side_effect=[char, other])

        response = client.get(f"/api/v1/characters/{char.id}/relations")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["from_name"] == "林尘"
        assert item["to_name"] == "青云真人"
        assert item["relation_type"] == "师徒"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_relation_success(self, mock_get_svc: MagicMock) -> None:
        """更新关系返回 200 + CharacterRelation JSON."""
        svc = _mock_svc(mock_get_svc)
        char = _char("林尘")
        other = _char("青云真人")
        rel = _rel(char, other, relation_type="师徒", description="新描述")
        svc.update_relation = AsyncMock(return_value=rel)

        response = client.patch(
            f"/api/v1/characters/{char.id}/relations/{rel.id}",
            json={"description": "新描述"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "新描述"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_relation_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的关系返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_relation = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/characters/{uuid.uuid4()}/relations/{uuid.uuid4()}",
            json={"description": "x"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "关系不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_relation_success(self, mock_get_svc: MagicMock) -> None:
        """删除关系返回 204."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_relation = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/characters/{uuid.uuid4()}/relations/{uuid.uuid4()}")
        assert response.status_code == 204

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_relation_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的关系返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_relation = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/characters/{uuid.uuid4()}/relations/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "关系不存在"


class TestGroupAPI:
    """角色分组端点测试."""

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_group_success(self, mock_get_svc: MagicMock) -> None:
        """创建分组返回 201 + CharacterGroup JSON."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        svc.create_group = AsyncMock(return_value=group)

        response = client.post(
            f"/api/v1/projects/{PID}/character-groups",
            json={"name": "主角团", "description": "主角及其伙伴", "sort_order": 1},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "主角团"
        assert data["sort_order"] == 1
        svc.create_group.assert_awaited_once_with(PID, "主角团", "主角及其伙伴", 1)

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_group_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名活动分组创建返回 422."""
        svc = _mock_svc(mock_get_svc)
        svc.create_group = AsyncMock(side_effect=GroupNameConflictError())

        response = client.post(f"/api/v1/projects/{PID}/character-groups", json={"name": "主角团"})
        assert response.status_code == 422
        assert response.json()["detail"] == "同名分组已存在（分组名在项目内必须唯一）"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_list_groups_success_with_member_count(self, mock_get_svc: MagicMock) -> None:
        """分组列表返回 200，含 member_count（spec §3.3）."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        svc.list_groups = AsyncMock(return_value=[group])
        svc.list_characters = AsyncMock(return_value=([], 3))

        response = client.get(f"/api/v1/projects/{PID}/character-groups")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "主角团"
        assert data["items"][0]["member_count"] == 3

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_get_group_success_with_member_count(self, mock_get_svc: MagicMock) -> None:
        """分组详情返回 200，含 member_count."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        svc.get_group = AsyncMock(return_value=group)
        svc.list_characters = AsyncMock(return_value=([], 3))

        response = client.get(f"/api/v1/character-groups/{group.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "主角团"
        assert data["member_count"] == 3

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_get_group_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """分组不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.get_group = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/character-groups/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "分组不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_group_success(self, mock_get_svc: MagicMock) -> None:
        """更新分组返回 200 + CharacterGroup JSON."""
        svc = _mock_svc(mock_get_svc)
        group = _group("主角团")
        updated = group.model_copy(update={"name": "主角联盟"})
        svc.update_group = AsyncMock(return_value=updated)

        response = client.patch(f"/api/v1/character-groups/{group.id}", json={"name": "主角联盟"})
        assert response.status_code == 200
        assert response.json()["name"] == "主角联盟"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_group_success(self, mock_get_svc: MagicMock) -> None:
        """删除分组返回 204（v1.1 真删，无 force 参数）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_group = AsyncMock(return_value=True)

        gid = uuid.uuid4()
        response = client.delete(f"/api/v1/character-groups/{gid}")
        assert response.status_code == 204
        svc.delete_group.assert_awaited_once_with(gid)


class TestExtractAPI:
    """AI 提取端点测试."""

    def _extract_result(self) -> CharacterExtractionResult:
        return CharacterExtractionResult(
            created=[_char("林尘")],
            updated=[],
            relations_created=[],
            relations_updated=[],
            warnings=[],
            model="openai/gpt-4o",
        )

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_extract_success(self, mock_get_svc: MagicMock) -> None:
        """AI 提取返回 200 + CharacterExtractionResult JSON."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=self._extract_result())

        response = client.post(
            "/api/v1/characters/extract",
            json={"project_id": str(PID), "text": "林尘是青云宗弟子，与青云真人是师徒。"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "openai/gpt-4o"
        assert len(data["created"]) == 1
        assert data["created"][0]["name"] == "林尘"
        assert "warnings" in data

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_extract_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """提取时项目不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            "/api/v1/characters/extract",
            json={"project_id": str(PID), "text": "林尘与青云真人是师徒。"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_extract_llm_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 调用失败返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=LLMRequestError("LLM 调用失败", retries_exhausted=True))

        response = client.post(
            "/api/v1/characters/extract",
            json={"project_id": str(PID), "text": "林尘与青云真人是师徒。"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "LLM 调用失败，请稍后重试"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_extract_parse_failure_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 输出无法解析（重试后仍失败）返回 500."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=CharacterExtractionError())

        response = client.post(
            "/api/v1/characters/extract",
            json={"project_id": str(PID), "text": "林尘与青云真人是师徒。"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "角色提取失败: LLM 输出无法解析，请重试"


class TestCharacterCoverageGaps:
    """F9 覆盖率补齐：分组名校验 / validator None 分支 / None·False 防御."""

    def test_validate_group_name_blank(self) -> None:
        """空白分组名 → ValueError."""
        with pytest.raises(ValueError, match="分组名不能为空"):
            _validate_group_name("   ")

    def test_validate_group_name_too_long(self) -> None:
        """超过 50 字符的分组名 → ValueError."""
        with pytest.raises(ValueError, match="分组名不能超过 50 个字符"):
            _validate_group_name("长" * 51)

    def test_validate_group_name_strips(self) -> None:
        """合法分组名去空白后返回."""
        assert _validate_group_name("  主角团  ") == "主角团"

    def test_group_update_validate_name_none(self) -> None:
        """CharacterGroupUpdateBody.validate_name(None) 直接放行（None = 不修改）."""
        assert CharacterGroupUpdateBody.validate_name(None) is None

    def test_relation_update_validate_relation_type(self) -> None:
        """CharacterRelationUpdateBody.validate_relation_type：None 放行 + 合法值通过."""
        assert CharacterRelationUpdateBody.validate_relation_type(None) is None
        assert CharacterRelationUpdateBody.validate_relation_type("师徒") == "师徒"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_character_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的角色返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_character = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/characters/{uuid.uuid4()}", json={"goals": "x"})
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_group_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的分组返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update_group = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/character-groups/{uuid.uuid4()}", json={"name": "改名"})
        assert response.status_code == 404
        assert response.json()["detail"] == "分组不存在"

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_group_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的分组返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_group = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/character-groups/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "分组不存在"


class TestCharacterExtraAPI:
    """F43 P1 角色 extra API 透传契约（spec §3.2）— 创建/更新 body 带 extra 透传到 service.

    【RED 预期】CharacterCreateBody/CharacterUpdate 尚无 extra 字段 → body extra
    被 Pydantic 忽略 → 创建断言收到调用缺 extra kwarg（AssertionError）/ 更新断言
    CharacterUpdate.extra 属性访问 AttributeError = 断言失败形态。GREEN 后自动转绿。
    """

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_create_character_passes_extra(self, mock_get_svc: MagicMock) -> None:
        """POST body 带 extra → svc.create_character 收到 extra 参数（原样透传）."""
        svc = _mock_svc(mock_get_svc)
        svc.create_character = AsyncMock(return_value=_char("林尘"))

        response = client.post(
            f"/api/v1/projects/{PID}/characters",
            json={
                "name": "林尘",
                "personality": "坚韧",
                "extra": {"role_rank": "major", "groups": ["主角团"]},
            },
        )
        assert response.status_code == 201
        svc.create_character.assert_awaited_once_with(
            PID,
            "林尘",
            "坚韧",
            "",
            "",
            [],
            extra={"role_rank": "major", "groups": ["主角团"]},
        )

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_update_character_passes_extra(self, mock_get_svc: MagicMock) -> None:
        """PATCH body 带 extra → svc.update_character 收到 CharacterUpdate.extra（整体替换语义）."""
        svc = _mock_svc(mock_get_svc)
        svc.update_character = AsyncMock(return_value=_char("林尘"))

        response = client.patch(
            f"/api/v1/characters/{uuid.uuid4()}",
            json={"extra": {"role_rank": "major", "groups": ["主角团"]}},
        )
        assert response.status_code == 200
        update = svc.update_character.await_args.args[1]
        assert update.extra == {"role_rank": "major", "groups": ["主角团"]}
        assert "extra" in update.model_fields_set


# ══ P5 删除引用残留清理（#284 最后一批，spec §3.8）══
#
# API 面零变更（清理是 service/repo 内部行为）——C10 守护用例：
# DELETE /characters/{id} 调用链不变（204 + svc.delete_character 被调）。
# RED 阶段 PASS 是刻意的（守护，非失败用例）。


class TestP5DeleteCharacterAPIContract:
    """C10：API 面零变更守护——DELETE 端点调用链不受清理实现影响."""

    @patch("inkflow.api.routers.characters.get_character_service")
    def test_delete_character_keeps_204_contract(self, mock_get_svc: MagicMock) -> None:
        """删除角色仍返回 204；svc.delete_character 仍被调用（清理为内部行为，API 无感知）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_character = AsyncMock(return_value=True)

        char_id = uuid.uuid4()
        response = client.delete(f"/api/v1/characters/{char_id}")

        assert response.status_code == 204
        svc.delete_character.assert_awaited_once_with(char_id)
