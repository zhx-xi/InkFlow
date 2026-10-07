"""#1482 F37 增强单元测试 — 分类过滤 + 缺失分类自动创建（service 层）.

拆分原因: `test_copy_service.py` 已 737 行（贴 900 行护栏）→ 本增量独立成文件
（F35/F36 拆分先例；spec f37 v1.3 §8 已登记本文件）。

覆盖（spec f37 v1.3 §2 规则 9/10/11、§5.1 ③b/④b、§7 场景 13-15、§14.3 A7/A8）:
- 分类过滤：仅匹配分类条目被复制；其他分类零复制；空匹配 → 空报告 + warning（非错误）
- 缺失分类跳过（默认）：auto_create_categories 缺省（False）→ 跳过 + warning（#848 守卫既有语义）
- 缺失分类自动创建（opt-in）：auto_create_categories=True → 按源 kind 建分类 + 继续复制
- 同名分类每轮只解析/创建一次
- 不变量守门（当前即 PASS）：self_only / root 子树 / 恒有根目标 / 重复复制幂等
- 自动创建模式下 warnings 为空（无「未创建分类…已跳过」）

【RED 预期】copy() 尚无 category / auto_create_categories 参数 →
显式传参用例 TypeError: copy() got an unexpected keyword argument 'category'（FAILED）；
「不变量守门」与既有用例（只用既有参数）当前即 PASS，GREEN 后仍须 PASS。

依据: specs/f37-world-copy/spec.md（v1.3）§2/§5.1/§7/§13 M9/§14；issue #1482。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.copy import WorldCopyRequest, WorldCopyResult
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.copy_service import WorldCopyService

SOURCE_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000c1")
TARGET_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000c2")
TS = datetime(2026, 10, 7, 10, 0, 0)


def _setting(
    name: str, *, project_id: uuid.UUID = SOURCE_PID, parent_id: uuid.UUID | None = None, **kw
):
    """构造测试用世界观条目（工厂返回注解省略防 F821；字段口径同 test_copy_service.py）."""
    from inkflow.domain.models.world import WorldSetting

    values = {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "name": name,
        "category": "",
        "content": "",
        "extra": {"scale": 1.0},
        "is_deleted": False,
        "parent_id": parent_id,
        "created_at": TS,
        "updated_at": TS,
    }
    values.update(kw)
    return WorldSetting(**values)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 全部方法显式默认值（裸 AsyncMock 陷阱防护）.

    默认「目标分类已存在」（get_category_by_name → MagicMock 真值）；
    需要「目标缺分类」的用例自行覆写为 None / side_effect。
    """
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.list_all_active = AsyncMock(return_value=[])
    repo.list_descendants = AsyncMock(return_value=[])
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))  # 目标默认无根
    repo.get_category_by_name = AsyncMock(return_value=MagicMock())  # 分类默认存在
    repo.create_category = AsyncMock(return_value=MagicMock())
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 源/目标项目均存在."""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(side_effect=lambda pid: SimpleNamespace(id=pid))
    return repo


@pytest.fixture
def service(mock_repo, mock_project_repo) -> WorldCopyService:
    """被测 WorldCopyService（map_repo/asset_store 不装配 → 地图复制静默跳过，聚焦条目面）."""
    return WorldCopyService(repository=mock_repo, project_repo=mock_project_repo)


class TestCategoryFilter:
    """`category` 过滤（spec §2 规则 9、§5.1 ③b、§7 场景 13、§14.3 A7）."""

    async def test_only_matching_category_copied(self, service, mock_repo) -> None:
        """category="灵能体系" → 仅该类 2 条被复制，其他分类条目零复制."""
        a1 = _setting("灵能九阶", category="灵能体系")
        a2 = _setting("灵能本源", category="灵能体系")
        b1 = _setting("剑派甲", category="门派")
        mock_repo.list_all_active = AsyncMock(return_value=[a1, a2, b1])

        result = await service.copy(SOURCE_PID, TARGET_PID, category="灵能体系")

        assert [s.name for s in result.created] == ["灵能九阶", "灵能本源"]
        assert mock_repo.add.await_count == 2
        assert all(s.category == "灵能体系" for s in result.created)

    async def test_category_combines_with_root_subtree(self, service, mock_repo) -> None:
        """root + category 同用 → 交集语义（子树内仅该分类条目）."""
        country = _setting("根甲", category="总纲")
        a1 = _setting("灵能九阶", category="灵能体系", parent_id=country.id)
        b1 = _setting("剑派甲", category="门派", parent_id=country.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: country if sid == country.id else None)
        mock_repo.list_descendants = AsyncMock(return_value=[country, a1, b1])

        result = await service.copy(
            SOURCE_PID, TARGET_PID, root_setting_id=country.id, category="灵能体系"
        )

        assert [s.name for s in result.created] == ["灵能九阶"]

    async def test_no_match_returns_empty_report_with_warning(self, service, mock_repo) -> None:
        """过滤后空集合 → 200 空报告 + warning（非错误，spec §7 场景 13）."""
        mock_repo.list_all_active = AsyncMock(return_value=[_setting("剑派甲", category="门派")])

        result = await service.copy(SOURCE_PID, TARGET_PID, category="不存在的分类")

        assert result.created == []
        mock_repo.add.assert_not_awaited()
        assert any("不存在的分类" in w for w in result.warnings)


class TestMissingCategoryAutoCreate:
    """缺失分类自动创建 / 跳过（spec §2 规则 10、§5.1 ④b、§7 场景 14-15、§14.3 A8）."""

    @staticmethod
    def _missing_category_repo(mock_repo, *, source_kind: str = "abstract") -> None:
        """目标缺「灵能体系」、源侧同名分类实体 kind=source_kind."""
        src_cat = SimpleNamespace(name="灵能体系", kind=source_kind)
        mock_repo.get_category_by_name = AsyncMock(
            side_effect=lambda pid, name: None if pid == TARGET_PID else src_cat
        )

    async def test_auto_created_when_enabled_and_entry_copied(self, service, mock_repo) -> None:
        """缺分类 + opt-in 开 → 按源 kind 自动建分类 + 条目复制成功 + categories_created."""
        entry = _setting("灵能九阶", category="灵能体系")
        mock_repo.list_all_active = AsyncMock(return_value=[entry])
        self._missing_category_repo(mock_repo, source_kind="abstract")

        result = await service.copy(SOURCE_PID, TARGET_PID, auto_create_categories=True)

        assert [s.name for s in result.created] == ["灵能九阶"]
        assert result.categories_created == ["灵能体系"]
        assert result.warnings == []  # 不含「未创建分类…已跳过」
        assert result.skipped == []
        mock_repo.create_category.assert_awaited_once_with(TARGET_PID, "灵能体系", "abstract")

    async def test_source_category_without_entity_falls_back_geo(self, service, mock_repo) -> None:
        """源项目无该分类实体（字符串快照）→ kind 回落 geo（spec §2 规则 10）."""
        entry = _setting("灵能九阶", category="灵能体系")
        mock_repo.list_all_active = AsyncMock(return_value=[entry])
        mock_repo.get_category_by_name = AsyncMock(return_value=None)  # 源/目标均无实体

        result = await service.copy(SOURCE_PID, TARGET_PID, auto_create_categories=True)

        assert result.categories_created == ["灵能体系"]
        mock_repo.create_category.assert_awaited_once_with(TARGET_PID, "灵能体系", "geo")

    async def test_created_once_per_category_for_multiple_entries(self, service, mock_repo) -> None:
        """同分类多条 → create_category 只调用一次，两条均复制（缓存）。"""
        e1 = _setting("灵能九阶", category="灵能体系")
        e2 = _setting("灵能本源", category="灵能体系")
        mock_repo.list_all_active = AsyncMock(return_value=[e1, e2])
        self._missing_category_repo(mock_repo)

        result = await service.copy(SOURCE_PID, TARGET_PID, auto_create_categories=True)

        assert [s.name for s in result.created] == ["灵能九阶", "灵能本源"]
        assert result.categories_created == ["灵能体系"]
        mock_repo.create_category.assert_awaited_once()

    async def test_default_skips_with_warning(self, service, mock_repo) -> None:
        """默认（auto_create_categories 缺省 = False）→ 跳过 + 既有 warning，不建分类、不落库."""
        entry = _setting("灵能九阶", category="灵能体系")
        mock_repo.list_all_active = AsyncMock(return_value=[entry])
        mock_repo.get_category_by_name = AsyncMock(return_value=None)

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert result.created == []
        assert result.categories_created == []
        assert result.skipped == ["灵能九阶"]
        assert any("未创建分类" in w for w in result.warnings)
        mock_repo.create_category.assert_not_awaited()
        mock_repo.add.assert_not_awaited()

    async def test_category_already_present_no_create(self, service, mock_repo) -> None:
        """目标已有该分类 → 不创建、categories_created 空（默认路径不误建）."""
        entry = _setting("灵能九阶", category="灵能体系")
        mock_repo.list_all_active = AsyncMock(return_value=[entry])
        # mock_repo 默认 get_category_by_name → MagicMock（目标已有该分类）

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert [s.name for s in result.created] == ["灵能九阶"]
        assert result.categories_created == []
        mock_repo.create_category.assert_not_awaited()


class TestInvariantsUnchanged:
    """#1482 不变量守门：既有参数路径（无 category / 缺省 auto）行为零回归."""

    async def test_root_subtree_semantics_unchanged(self, service, mock_repo) -> None:
        """root 子树语义不变：list_descendants 返回什么就复制什么（缺省 auto 不影响）."""
        country = _setting("根甲", category="总纲")
        state = _setting("州甲", category="地理", parent_id=country.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state])

        result = await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=state.id)

        assert [s.name for s in result.created] == ["州甲"]
        mock_repo.list_descendants.assert_awaited_once_with(state.id)
        mock_repo.list_all_active.assert_not_awaited()

    async def test_self_only_semantics_unchanged(self, service, mock_repo) -> None:
        """self_only=True 语义不变：仅本体复制（不调 list_descendants）."""
        state = _setting("州甲", category="地理")
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state, _setting("县甲")])

        result = await service.copy(
            SOURCE_PID, TARGET_PID, root_setting_id=state.id, self_only=True
        )

        assert [s.name for s in result.created] == ["州甲"]
        mock_repo.list_descendants.assert_not_awaited()

    async def test_rooted_target_attaches_subtree_top_under_target_root(
        self, service, mock_repo
    ) -> None:
        """恒有根目标（#1493）：子树顶节点挂目标根下，复制条数不变."""
        target_root = _setting("目标根", project_id=TARGET_PID, category="总纲")
        country = _setting("根甲", category="总纲")
        state = _setting("州甲", category="地理", parent_id=country.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state])
        mock_repo.list = AsyncMock(return_value=([target_root], 1))

        result = await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=state.id)

        assert [s.name for s in result.created] == ["州甲"]
        assert result.created[0].parent_id == target_root.id

    async def test_repeat_copy_is_idempotent_no_overwrite(self, service, mock_repo) -> None:
        """重复复制幂等：第二次全部同名跳过、零新增、不覆盖（spec §2 规则 11）."""
        country = _setting("根甲", category="总纲")
        state = _setting("州甲", category="地理", parent_id=country.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state])
        mock_repo.get = AsyncMock(side_effect=lambda sid: country if sid == country.id else None)

        first = await service.copy(SOURCE_PID, TARGET_PID)
        assert [s.name for s in first.created] == ["根甲", "州甲"]
        assert mock_repo.add.await_count == 2

        # 目标已存在全部同名条目 → 第二次全部 skipped
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=MagicMock())
        mock_repo.add.reset_mock()

        second = await service.copy(SOURCE_PID, TARGET_PID)

        assert second.created == []
        assert second.skipped == ["根甲", "州甲"]
        mock_repo.add.assert_not_awaited()


class TestCategoryDtos:
    """DTO 契约（spec §2）：请求新字段默认值 + 结果新报告键."""

    def test_request_defaults(self) -> None:
        """WorldCopyRequest: category 缺省 None、auto_create_categories 缺省 False（opt-in）."""
        req = WorldCopyRequest(source_project_id=SOURCE_PID)
        assert req.category is None
        assert req.auto_create_categories is False

    def test_request_accepts_explicit_values(self) -> None:
        """显式传 category / auto_create_categories=True（opt-in）被接受."""
        req = WorldCopyRequest(
            source_project_id=SOURCE_PID,
            category="灵能体系",
            auto_create_categories=True,
        )
        assert req.category == "灵能体系"
        assert req.auto_create_categories is True

    def test_result_exposes_categories_created(self) -> None:
        """WorldCopyResult.categories_created 为报告键（缺省路径为空列表）."""
        result = WorldCopyResult(
            created=[],
            skipped=[],
            maps_created=[],
            pins_created=0,
            warnings=[],
            categories_created=["灵能体系"],
        )
        assert result.categories_created == ["灵能体系"]
        assert result.model_dump(mode="json")["categories_created"] == ["灵能体系"]
