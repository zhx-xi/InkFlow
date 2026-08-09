"""F22 全文搜索 DTO 模型单元测试 — 纯 Pydantic 校验，无 I/O.

RED 阶段：inkflow/domain/models/search.py 不存在 → 收集期 ModuleNotFoundError
即预期失败形态（collected 0 items + 1 error，exit 2）。

测试范围（spec §2.2/§6.3/§3.3）：SearchMode / SearchEntityType 枚举值、SearchQuery
必填与边界（q 空白/超长、project_ids 必填、types 枚举与 [] 归一 None、mode 默认、
limit 边界）、SearchHit 默认 score、SearchResponse 完整 roundtrip。

依据: specs/f22-search-service/spec.md §2.2（DTO 定义）/ §6.3（types=[] 语义）/
§3.3（422 校验场景）。

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- 模块路径: inkflow/domain/models/search.py（spec §8.1 CREATE 清单），导出
  SearchMode / SearchEntityType / SearchQuery / SearchHit / SearchResponse。
- SearchMode(StrEnum)：KEYWORD="keyword" / SEMANTIC="semantic"（§2.2，keyword 默认）。
- SearchEntityType(StrEnum) 六值：chapter / character / world / outline /
  timeline / foreshadowing（§2.1，与 F21 附录类型集对齐）。
- SearchQuery:
  - q: str 必填，min_length=1 / max_length=100；须有 strip validator——strip 后空
    （纯空白）→ ValidationError（§3.3「q 缺失/空白/超长 → 422」）；strip 后非空
    （如 " 龙 "）合法。长度按原始字符计：100 接受、101 拒绝。
  - project_ids: list[uuid.UUID] 必填（缺省 → ValidationError）；非法 UUID 拒绝；
    UUID 字符串可被 pydantic v2 强制转换。
  - types: list[SearchEntityType] | None = None；空列表 [] → validator 归一为 None
    （§6.3 客户端省略参数的自然形态）；None 合法；str 枚举名（"chapter"）可转换。
  - mode: SearchMode = SearchMode.KEYWORD；非法枚举拒绝。
  - limit: int = 20，ge=1 / le=100（0/101 拒绝，1/100 接受）；offset: int = 0。
- SearchHit: entity_type / entity_id / project_id / title / snippet 必填；
  score: float = 0.0（默认 0.0）。
- SearchResponse: total / hits / query / types / mode / project_ids 全必填
  （§2.2 无默认值）；model_dump(mode="json") 序列化 UUID/枚举为 str；
  model_validate(model_dump()) roundtrip 恒等。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from inkflow.domain.models.search import (
    SearchEntityType,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchResponse,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID2 = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
EID = uuid.UUID("3f2e1d4a-0000-4000-8000-00000000000a")


def _query(**overrides: Any) -> SearchQuery:
    """构造合法 SearchQuery（默认值可覆盖，spec §3.2 示例同形态）."""
    base: dict[str, Any] = {
        "q": "龙",
        "project_ids": [PID],
    }
    base.update(overrides)
    return SearchQuery(**base)


def _hit(**overrides: Any) -> SearchHit:
    """构造完整 SearchHit（默认值可覆盖，spec §3.2 示例同形态）."""
    base: dict[str, Any] = {
        "entity_type": SearchEntityType.CHAPTER,
        "entity_id": EID,
        "project_id": PID,
        "title": "第 3 章 龙的苏醒",
        "snippet": "古井深处，<mark>龙</mark>瞳睁开。",
    }
    base.update(overrides)
    return SearchHit(**base)


def _response(**overrides: Any) -> SearchResponse:
    """构造完整 SearchResponse（默认值可覆盖，spec §3.2 示例同形态）."""
    base: dict[str, Any] = {
        "total": 1,
        "hits": [_hit()],
        "query": "龙",
        "types": [SearchEntityType.CHAPTER],
        "mode": SearchMode.KEYWORD,
        "project_ids": [PID],
    }
    base.update(overrides)
    return SearchResponse(**base)


class TestSearchMode:
    """SearchMode 枚举（§2.2：keyword 默认 / semantic 增强）."""

    def test_keyword_and_semantic_values(self) -> None:
        """两个成员的值分别为 keyword / semantic，且可按值反查."""
        assert SearchMode.KEYWORD.value == "keyword"
        assert SearchMode.SEMANTIC.value == "semantic"
        assert SearchMode("keyword") is SearchMode.KEYWORD
        assert SearchMode("semantic") is SearchMode.SEMANTIC


class TestSearchEntityType:
    """SearchEntityType 六值枚举（§2.1 类型集）."""

    def test_six_values(self) -> None:
        """六类可搜索内容类型，值按 spec §2.1 表逐字."""
        assert [t.value for t in SearchEntityType] == [
            "chapter",
            "character",
            "world",
            "outline",
            "timeline",
            "foreshadowing",
        ]


class TestSearchQuery:
    """SearchQuery 必填与边界校验（§2.2 + §3.3 422 场景）."""

    def test_q_required(self) -> None:
        """缺省 q → ValidationError（§3.3「q 缺失 → 422」）."""
        with pytest.raises(ValidationError):
            SearchQuery(project_ids=[PID])

    def test_q_blank_rejected(self) -> None:
        """空串与纯空白（空格/制表/换行）→ ValidationError（strip 后拒绝）."""
        for q in ("", "   ", "\t  \n", "　　"):  # 含全角空格
            with pytest.raises(ValidationError):
                _query(q=q)

    def test_q_whitespace_padded_accepted(self) -> None:
        """strip 后非空的空白包裹查询词合法（如 " 龙 "）."""
        model = _query(q=" 龙 ")
        assert model.q.strip() == "龙"

    def test_q_max_length_100_accepted(self) -> None:
        """100 字符边界接受."""
        _query(q="a" * 100)

    def test_q_length_101_rejected(self) -> None:
        """101 字符超长 → ValidationError（§3.3「q 超长 → 422」）."""
        with pytest.raises(ValidationError):
            _query(q="a" * 101)

    def test_project_ids_required(self) -> None:
        """缺省 project_ids → ValidationError（§2.2 必填）."""
        with pytest.raises(ValidationError):
            SearchQuery(q="龙")

    def test_project_ids_invalid_uuid_rejected(self) -> None:
        """非法 UUID 字符串 → ValidationError."""
        with pytest.raises(ValidationError):
            _query(project_ids=["not-a-uuid"])

    def test_project_ids_uuid_string_coerced(self) -> None:
        """合法 UUID 字符串被 pydantic 强制转换为 uuid.UUID."""
        model = _query(project_ids=["3f2e1d4a-0000-4000-8000-000000000001"])
        assert model.project_ids == [PID]

    def test_types_default_none(self) -> None:
        """types 缺省 → None（全部类型，§6.3）."""
        assert _query().types is None

    def test_types_none_valid(self) -> None:
        """types=None 显式合法."""
        assert _query(types=None).types is None

    def test_types_empty_list_normalized_to_none(self) -> None:
        """types=[] → validator 归一为 None（§6.3 客户端省略参数的自然形态）."""
        model = _query(types=[])
        assert model.types is None

    def test_types_enum_and_str_accepted(self) -> None:
        """枚举成员与 str 枚举名均可传入，统一归一为枚举列表."""
        model = _query(types=[SearchEntityType.CHAPTER, "world"])
        assert model.types == [SearchEntityType.CHAPTER, SearchEntityType.WORLD]

    def test_types_invalid_rejected(self) -> None:
        """非法枚举值 → ValidationError（§3.3「types 非法枚举 → 422」）."""
        with pytest.raises(ValidationError):
            _query(types=["bogus"])

    def test_mode_default_keyword(self) -> None:
        """mode 缺省 → SearchMode.KEYWORD（§2.2 keyword 默认）."""
        assert _query().mode is SearchMode.KEYWORD

    def test_mode_semantic_accepted(self) -> None:
        """mode="semantic" 合法（v1.1 AI 语义增强）."""
        assert _query(mode="semantic").mode is SearchMode.SEMANTIC

    def test_mode_invalid_rejected(self) -> None:
        """非法 mode → ValidationError（§3.3「mode 非法 → 422」）."""
        with pytest.raises(ValidationError):
            _query(mode="bogus")

    def test_limit_default_20(self) -> None:
        """limit 缺省 → 20（§2.2）."""
        assert _query().limit == 20

    @pytest.mark.parametrize("limit", [1, 100])
    def test_limit_boundaries_accepted(self, limit: int) -> None:
        """limit 边界 1/100 接受."""
        assert _query(limit=limit).limit == limit

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_out_of_range_rejected(self, limit: int) -> None:
        """limit 越界 0/101 → ValidationError（§3.3「limit 越界 → 422」）."""
        with pytest.raises(ValidationError):
            _query(limit=limit)

    def test_offset_default_0(self) -> None:
        """offset 缺省 → 0（§2.2）."""
        assert _query().offset == 0


class TestSearchHit:
    """SearchHit 必填字段与默认 score（§2.2）."""

    def test_all_fields_required(self) -> None:
        """全字段缺省 → ValidationError（entity_type/entity_id/project_id/title/snippet 必填）."""
        with pytest.raises(ValidationError):
            SearchHit()

    def test_score_default_zero(self) -> None:
        """score 缺省 → 0.0（§2.2 相关度默认）."""
        assert _hit().score == 0.0

    def test_score_explicit_value(self) -> None:
        """score 显式传入保留（BM25 rank / 余弦相似度，§5.6）."""
        assert _hit(score=3.2).score == 3.2

    def test_json_roundtrip(self) -> None:
        """model_dump(mode="json") 后 UUID/枚举为 str，回灌构造恒等."""
        hit = _hit()
        dumped = hit.model_dump(mode="json")
        assert isinstance(dumped["entity_type"], str)
        assert dumped["entity_type"] == "chapter"
        assert isinstance(dumped["entity_id"], str)
        assert dumped["entity_id"] == str(EID)
        assert SearchHit(**dumped) == hit


class TestSearchResponse:
    """SearchResponse 完整 dump 与 roundtrip（§2.2 + §3.2 示例形态）."""

    def test_full_roundtrip(self) -> None:
        """model_validate(model_dump()) 恒等（含多项目 + semantic + 双类型）."""
        resp = _response(
            mode=SearchMode.SEMANTIC,
            types=[SearchEntityType.CHAPTER, SearchEntityType.WORLD],
            project_ids=[PID, PID2],
        )
        assert SearchResponse.model_validate(resp.model_dump()) == resp

    def test_json_dump_serializes_strs(self) -> None:
        """JSON dump 全部 UUID/枚举序列化为 str（§3.2 响应示例形态）."""
        resp = _response(
            mode="semantic",
            types=["chapter", "world"],
            project_ids=[PID, PID2],
        )
        dumped = resp.model_dump(mode="json")
        assert dumped["mode"] == "semantic"
        assert dumped["types"] == ["chapter", "world"]
        assert dumped["project_ids"] == [str(PID), str(PID2)]
        assert dumped["hits"][0]["entity_id"] == str(EID)
        assert dumped["hits"][0]["entity_type"] == "chapter"

    def test_types_none_json_dump(self) -> None:
        """types=None 在 JSON dump 中保持 null（回显筛选语义，§2.2）."""
        dumped = _response(types=None).model_dump(mode="json")
        assert dumped["types"] is None
        assert SearchResponse.model_validate(dumped) == _response(types=None)

    def test_query_echo_and_total(self) -> None:
        """query 回显原始查询词、total 不受 limit 影响（§2.2 注释口径）."""
        resp = _response(query="龙的苏醒", total=42, hits=[_hit(), _hit()])
        assert resp.query == "龙的苏醒"
        assert resp.total == 42
        assert len(resp.hits) == 2
