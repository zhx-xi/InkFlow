"""#1360 drawio（mxGraph XML）导入/导出 — service + 编解码 RED 契约测试（M9）.

GREEN 必须匹配的契约（specs/f48-knowledge-graph/spec.md §5.7，ADR-061）:

【新增模块】inkflow.domain.services._mxgraph_codec（纯函数，仅标准库 xml.etree）
- MXGRAPH_FORMAT: str = "mxgraph"
- build_mxgraph_xml(nodes: list[GraphNode], edges: list[GraphEdge]) -> str
    * 三层结构 mxfile > diagram > mxGraphModel > root（root 内 id="0" / id="1" parent="0"）
    * 节点：朴素 mxCell，id = f"{node.type.value}:{node.entity_id}"，value = node.name，
      确定性网格坐标 x = 40 + col*200 / y = 40 + row*60
      （col = 类型序 character0 world1 outline2 timeline3 foreshadow4 map_pin5，row = 该类型内序号）
    * 边：<object id="kr:<edge.id 去 kr: 前缀>" label=relation_type tooltip=description> 包 mxCell
      （edge="1" source/target = 节点 id；description 为空 → **省略 tooltip 属性**）
    * 纯函数：同输入两次调用**字节级一致**（无时间戳/随机/无序 dict 迭代）
    * 文本一律 XML 转义（name/label 含 & < > " 时不得产出非法 XML）
- parse_mxgraph_xml(xml: str) -> list[MxGraphEdge]
    * 认 mxCell 与 <object>/<UserObject> 包装的 mxCell 两种形态（drawio 保存都会出现）
    * 边判定：edge="1" 或（同时有 source + target）
    * label = 包装元素 label 优先，否则 mxCell value；description = 包装元素 tooltip（缺省 ""）
    * 端点为原始 cell id 字符串（**不解析**——解析在 parse_entity_ref）
    * 非法 XML / 根不是 mxfile|mxGraphModel / 找不到 mxGraphModel / 空串
      → MxGraphImportError（message 以「非法 mxGraph XML」开头）
- parse_entity_ref(cell_id: str) -> tuple[EntityType, uuid.UUID] | None
    * 按**第一个** ":" 拆分；type 必须 ∈ EntityType 六值且 uuid 可解析，否则 None
- suggest_drawio_filename(project_name: str) -> str
    * strip 后为空 → "untitled-knowledge-graph.drawio"
    * Windows 禁符 \\ / : * ? " < > | → "_"；书名截断 60 字符；后缀恒 "-knowledge-graph.drawio"

【领域模型追加】inkflow.domain.models.knowledge_graph
- MxGraphEdge(id: str, label: str, description: str = "", source: str, target: str)
- KnowledgeGraphImportIssue(kind: Literal["skipped","failed"], edge_id, label, reason)
- KnowledgeGraphImportResult(mode, total, imported, skipped, failed, deleted=0, details=[])

【错误类追加】inkflow.domain.ports.knowledge_graph_errors.MxGraphImportError
  （继承 KnowledgeGraphServiceError → API 422）

【端口追加】KnowledgeRelationRepositoryProtocol.delete_by_project(project_id) -> int

【服务方法追加】KnowledgeGraphService
- export_mxgraph(project_id) -> tuple[str, str]      # (xml, filename)
    * 项目不存在 → ProjectNotFoundError
    * 节点集 = **参与至少一条关系的实体端点并集**（无关系 → 0 节点 0 边）
    * 端点实体查不到（已删）→ 跳过该边 + warning（不抛、不生成悬空引用）
    * 节点序复用 §5.6 图谱节点序（六类组序 + 组内 name ASC）
- import_mxgraph(project_id, xml, mode="merge") -> KnowledgeGraphImportResult
    * 先 parse（解析失败 → MxGraphImportError，**数据零变更**：replace 也不删）
    * 每条可解析边 → 组装六元组 + description → **复用 create_relation**（§5.1 校验链）
      - 同键已存在（库内既有 / 文件内重复）→ KnowledgeRelationConflictError → skipped
      - 自环 / 实体不存在或跨项目 / 字段非法 → KnowledgeGraphServiceError → failed + reason
      - 端点无法 parse_entity_ref → failed（reason 含「端点无法解析」），不进校验链
    * mode="replace"：解析成功后**先** relation_repo.delete_by_project(pid)（→ deleted），
      再逐边写入；mode="merge"：deleted 恒 0
    * 单行非法**不中断整批、不抛**（HTTP 层仍 200）
    * 恒等式 total == imported + skipped + failed（total = 文件内边 cell 总数）
    * source 列恒 manual

依据: specs/f48-knowledge-graph/spec.md §5.7/§3.3/§7 边界 18-25/§9 场景 18-22/§13 M9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import Character
from inkflow.domain.models.knowledge_graph import (
    EntityType,
    GraphEdge,
    GraphNode,
    KnowledgeRelation,
)
from inkflow.domain.models.project import Project
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeGraphServiceError,
    MxGraphImportError,
)
from inkflow.domain.ports.knowledge_relation_repository import (
    KnowledgeRelationRepositoryProtocol,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services import _mxgraph_codec
from inkflow.domain.services.knowledge_graph_service import KnowledgeGraphService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

CHAR_ID = uuid.UUID("0a000000-0000-4000-8000-0000000000c1")
CHAR2_ID = uuid.UUID("0a000000-0000-4000-8000-0000000000c2")
WORLD_ID = uuid.UUID("0b000000-0000-4000-8000-0000000000d1")


# ── 构造器 ─────────────────────────────────────────────────────────


def _node(entity_type: EntityType, entity_id: uuid.UUID, name: str) -> GraphNode:
    return GraphNode(
        id=f"{entity_type.value}:{entity_id}", type=entity_type, entity_id=entity_id, name=name
    )


def _edge(
    *,
    source: str,
    target: str,
    label: str = "师承",
    description: str = "",
    relation_id: uuid.UUID | None = None,
) -> GraphEdge:
    """构造图谱边（id 恒 kr:<uuid>，同 §2.4）。"""
    rid = relation_id or uuid.uuid4()
    return GraphEdge(
        id=f"kr:{rid}",
        source=source,
        target=target,
        label=label,
        description=description,
        source_table="knowledge_relations",
    )


def _char(name: str, *, project_id: uuid.UUID = PID, cid: uuid.UUID | None = None) -> Character:
    return Character(
        id=cid or uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS
    )


def _world(name: str, *, project_id: uuid.UUID = PID, wid: uuid.UUID | None = None) -> WorldSetting:
    return WorldSetting(
        id=wid or uuid.uuid4(), project_id=project_id, name=name, created_at=TS, updated_at=TS
    )


def _project(name: str = "项目甲") -> Project:
    return Project(id=PID, name=name, created_at=TS, updated_at=TS)


def _kr(
    *,
    source_type: str = "character",
    source_id: uuid.UUID,
    target_type: str = "world",
    target_id: uuid.UUID,
    relation_type: str = "师承",
    description: str = "",
) -> KnowledgeRelation:
    return KnowledgeRelation(
        id=uuid.uuid4(),
        project_id=PID,
        source_type=EntityType(source_type),
        source_id=source_id,
        target_type=EntityType(target_type),
        target_id=target_id,
        relation_type=relation_type,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _wrap(*cells: str) -> str:
    """把若干 cell 片段包进合法 mxfile 骨架（测试自造输入用，独立于 build_mxgraph_xml）。"""
    body = "\n".join(cells)
    model = (
        '<mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1"'
        ' pageWidth="850" pageHeight="1100">'
    )
    return (
        '<mxfile host="InkFlow" type="device">'
        '<diagram id="inkflow-knowledge-graph" name="知识图谱">'
        f"{model}"
        f'<root><mxCell id="0" /><mxCell id="1" parent="0" />{body}</root>'
        "</mxGraphModel></diagram></mxfile>"
    )


def _node_cell(cell_id: str, value: str) -> str:
    geometry = '<mxGeometry x="40" y="40" width="140" height="40" as="geometry" />'
    return (
        f'<mxCell id="{cell_id}" value="{value}" style="rounded=1;whiteSpace=wrap;html=1;" '
        f'vertex="1" parent="1">{geometry}</mxCell>'
    )


def _edge_cell(
    edge_id: str, label: str, source: str, target: str, *, tooltip: str | None = None
) -> str:
    """drawio 形态边：<object> 包装（可选 tooltip 属性）。"""
    tooltip_attr = f' tooltip="{tooltip}"' if tooltip is not None else ""
    cell = (
        '<mxCell style="edgeStyle=orthogonalEdgeStyle;html=1;endArrow=classic;"'
        f' edge="1" parent="1" source="{source}" target="{target}">'
        '<mxGeometry relative="1" as="geometry" /></mxCell>'
    )
    return f'<object id="{edge_id}" label="{label}"{tooltip_attr}>{cell}</object>'


# ── Mock fixtures（镜像 test_knowledge_graph_service.py 形态） ────────


@pytest.fixture
def mock_relation_repo() -> MagicMock:
    repo = MagicMock(spec=KnowledgeRelationRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda r: r)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_key = AsyncMock(return_value=None)
    repo.list_by_project = AsyncMock(return_value=[])
    repo.delete_by_project = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_character_repo() -> MagicMock:
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_world_repo() -> MagicMock:
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def svc(mock_relation_repo, mock_project_repo, mock_character_repo, mock_world_repo):
    """被测服务（只注入本文件用到的三类 repo；其余实体类 repo 未注入 → 空）。"""
    return KnowledgeGraphService(
        relation_repo=mock_relation_repo,
        project_repo=mock_project_repo,
        character_repo=mock_character_repo,
        world_repo=mock_world_repo,
    )


# ═══════════════════════════════════════════════════════════════════
# A. 编解码纯函数
# ═══════════════════════════════════════════════════════════════════


class TestBuildMxGraphXml:
    """导出：GraphNode/GraphEdge → mxGraph XML。"""

    def test_xml_has_three_layer_skeleton_and_root_cells(self) -> None:
        xml = _mxgraph_codec.build_mxgraph_xml(
            [_node(EntityType.CHARACTER, CHAR_ID, "角色甲")],
            [_edge(source=f"character:{CHAR_ID}", target=f"world:{WORLD_ID}", label="属于")],
        )
        assert xml.startswith("<mxfile")
        assert "<diagram" in xml
        assert "<mxGraphModel" in xml
        assert '<mxCell id="0" />' in xml
        assert '<mxCell id="1" parent="0" />' in xml

    def test_node_cell_id_and_value_mapping(self) -> None:
        xml = _mxgraph_codec.build_mxgraph_xml([_node(EntityType.CHARACTER, CHAR_ID, "角色甲")], [])
        assert f'id="character:{CHAR_ID}"' in xml
        assert 'value="角色甲"' in xml
        assert 'vertex="1"' in xml

    def test_edge_wrapped_in_object_with_label_and_tooltip(self) -> None:
        rid = uuid.UUID("0e000000-0000-4000-8000-0000000000e1")
        xml = _mxgraph_codec.build_mxgraph_xml(
            [
                _node(EntityType.CHARACTER, CHAR_ID, "角色甲"),
                _node(EntityType.WORLD, WORLD_ID, "门派乙"),
            ],
            [
                _edge(
                    source=f"character:{CHAR_ID}",
                    target=f"world:{WORLD_ID}",
                    label="属于",
                    description="出身地",
                    relation_id=rid,
                )
            ],
        )
        assert f'<object id="kr:{rid}"' in xml
        assert 'label="属于"' in xml
        assert 'tooltip="出身地"' in xml
        assert f'source="character:{CHAR_ID}"' in xml
        assert f'target="world:{WORLD_ID}"' in xml

    def test_empty_description_omits_tooltip_attribute(self) -> None:
        xml = _mxgraph_codec.build_mxgraph_xml(
            [_node(EntityType.CHARACTER, CHAR_ID, "角色甲")],
            [_edge(source=f"character:{CHAR_ID}", target=f"world:{WORLD_ID}", label="属于")],
        )
        assert "tooltip=" not in xml

    def test_two_calls_are_byte_identical(self) -> None:
        nodes = [
            _node(EntityType.CHARACTER, CHAR_ID, "角色甲"),
            _node(EntityType.WORLD, WORLD_ID, "门派乙"),
        ]
        edges = [_edge(source=f"character:{CHAR_ID}", target=f"world:{WORLD_ID}", label="属于")]
        assert _mxgraph_codec.build_mxgraph_xml(nodes, edges) == _mxgraph_codec.build_mxgraph_xml(
            nodes, edges
        )

    def test_node_coordinate_grid_is_deterministic(self) -> None:
        nodes = [
            _node(EntityType.CHARACTER, CHAR_ID, "角色甲"),
            _node(EntityType.CHARACTER, CHAR2_ID, "角色乙"),
            _node(EntityType.WORLD, WORLD_ID, "门派乙"),
        ]
        xml = _mxgraph_codec.build_mxgraph_xml(nodes, [])
        # character = col 0 → x=40；world = col 1 → x=240；character 第二行 → y=100
        assert 'x="40" y="40"' in xml
        assert 'x="40" y="100"' in xml
        assert 'x="240" y="40"' in xml

    def test_special_chars_are_xml_escaped(self) -> None:
        xml = _mxgraph_codec.build_mxgraph_xml(
            [_node(EntityType.CHARACTER, CHAR_ID, '甲<&>"引"')],
            [_edge(source=f"character:{CHAR_ID}", target=f"world:{WORLD_ID}", label="a&b<c")],
        )
        assert "甲<&>" not in xml  # 裸字符不得出现
        assert "&lt;" in xml and "&amp;" in xml
        # 回读等价
        edges = _mxgraph_codec.parse_mxgraph_xml(xml)
        assert edges[0].label == "a&b<c"

    def test_empty_graph_produces_valid_empty_file(self) -> None:
        xml = _mxgraph_codec.build_mxgraph_xml([], [])
        assert 'vertex="1"' not in xml
        assert 'edge="1"' not in xml
        assert _mxgraph_codec.parse_mxgraph_xml(xml) == []


class TestSuggestDrawioFilename:
    """导出文件名建议（Windows 禁符清洗 + 后缀）。"""

    def test_normal_project_name(self) -> None:
        assert _mxgraph_codec.suggest_drawio_filename("项目甲") == "项目甲-knowledge-graph.drawio"

    def test_blank_name_falls_back_to_untitled(self) -> None:
        assert _mxgraph_codec.suggest_drawio_filename("   ") == "untitled-knowledge-graph.drawio"

    def test_forbidden_chars_replaced_one_by_one(self) -> None:
        assert _mxgraph_codec.suggest_drawio_filename('a/b\\c:d*e?f"g<h>i|j') == (
            "a_b_c_d_e_f_g_h_i_j-knowledge-graph.drawio"
        )

    def test_name_truncated_to_60_chars(self) -> None:
        got = _mxgraph_codec.suggest_drawio_filename("字" * 80)
        assert got == "字" * 60 + "-knowledge-graph.drawio"


class TestParseMxGraphXml:
    """导入：mxGraph XML → 边 cell 列表。"""

    def test_parse_object_wrapped_edge(self) -> None:
        xml = _wrap(
            _node_cell(f"character:{CHAR_ID}", "角色甲"),
            _edge_cell(
                "kr:k1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}", tooltip="出身地"
            ),
        )
        edges = _mxgraph_codec.parse_mxgraph_xml(xml)
        assert len(edges) == 1
        assert edges[0].label == "属于"
        assert edges[0].description == "出身地"
        assert edges[0].source == f"character:{CHAR_ID}"
        assert edges[0].target == f"world:{WORLD_ID}"

    def test_parse_plain_mxcell_edge(self) -> None:
        cell = (
            f'<mxCell id="kr:k2" value="师徒" edge="1" parent="1" '
            f'source="character:{CHAR_ID}" target="character:{CHAR2_ID}" />'
        )
        edges = _mxgraph_codec.parse_mxgraph_xml(_wrap(cell))
        assert len(edges) == 1
        assert edges[0].label == "师徒"
        assert edges[0].description == ""

    def test_cell_with_source_target_but_no_edge_attr_is_edge(self) -> None:
        cell = (
            f'<mxCell id="kr:k3" value="同门" parent="1" '
            f'source="character:{CHAR_ID}" target="character:{CHAR2_ID}" />'
        )
        assert len(_mxgraph_codec.parse_mxgraph_xml(_wrap(cell))) == 1

    def test_vertex_and_structural_cells_are_not_edges(self) -> None:
        xml = _wrap(_node_cell(f"character:{CHAR_ID}", "角色甲"))
        assert _mxgraph_codec.parse_mxgraph_xml(xml) == []

    def test_invalid_xml_raises_import_error(self) -> None:
        with pytest.raises(MxGraphImportError) as ei:
            _mxgraph_codec.parse_mxgraph_xml("<mxfile><diagram></mxfile>")
        assert str(ei.value).startswith("非法 mxGraph XML")

    def test_missing_model_raises_import_error(self) -> None:
        with pytest.raises(MxGraphImportError):
            _mxgraph_codec.parse_mxgraph_xml("<foo><bar /></foo>")

    def test_empty_string_raises_import_error(self) -> None:
        with pytest.raises(MxGraphImportError):
            _mxgraph_codec.parse_mxgraph_xml("")

    def test_compressed_drawio_raises_readable_hint(self) -> None:
        """drawio「导出为 XML + Compressed」= <diagram> 内 base64 压缩体（无 mxGraphModel）.

        这是真实存在的保存形态（drawio 官方文档：导出 XML 时 Compressed 默认勾选）；
        错误信息必须点明「压缩」，否则用户无从下手（.drawio 直接保存默认未压缩，可用）。
        """
        xml = (
            '<mxfile host="app.diagrams.net"><diagram id="a" name="知识图谱">'
            "X9ldYQlm0iTQi9OQ1m0aB1cV8fZ2Y3J4K5L6M7N8P9Q0R1S2T3U4V5W6X7Y8Z9a0b1c2d3e4f5"
            "</diagram></mxfile>"
        )
        with pytest.raises(MxGraphImportError) as ei:
            _mxgraph_codec.parse_mxgraph_xml(xml)
        assert "压缩" in str(ei.value)

    def test_empty_diagram_still_reports_missing_model(self) -> None:
        """反例守护：空 <diagram> 不含压缩正文 → 仍报「缺少 mxGraphModel」（不误报压缩）。"""
        with pytest.raises(MxGraphImportError) as ei:
            _mxgraph_codec.parse_mxgraph_xml('<mxfile><diagram id="a" name="p" /></mxfile>')
        assert "压缩" not in str(ei.value)

    def test_import_error_is_422_base_subclass(self) -> None:
        assert issubclass(MxGraphImportError, KnowledgeGraphServiceError)


class TestParseEntityRef:
    """cell id → (EntityType, uuid) 解析。"""

    def test_six_entity_types_parse(self) -> None:
        for et in EntityType:
            ref = _mxgraph_codec.parse_entity_ref(f"{et.value}:{CHAR_ID}")
            assert ref == (et, CHAR_ID)

    def test_unknown_type_returns_none(self) -> None:
        assert _mxgraph_codec.parse_entity_ref(f"bogus:{CHAR_ID}") is None

    def test_invalid_uuid_returns_none(self) -> None:
        assert _mxgraph_codec.parse_entity_ref("character:not-a-uuid") is None

    def test_hand_drawn_cell_id_returns_none(self) -> None:
        assert _mxgraph_codec.parse_entity_ref("X1a2b3c") is None

    def test_empty_uuid_returns_none(self) -> None:
        assert _mxgraph_codec.parse_entity_ref("character:") is None


# ═══════════════════════════════════════════════════════════════════
# B. 服务层
# ═══════════════════════════════════════════════════════════════════


class TestExportMxgraph:
    """service.export_mxgraph(project_id) -> (xml, filename)。"""

    @pytest.mark.asyncio
    async def test_export_missing_project_raises_not_found(self, svc, mock_project_repo) -> None:
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await svc.export_mxgraph(PID)

    @pytest.mark.asyncio
    async def test_export_includes_relations_endpoints_and_filename(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        char = _char("角色甲", cid=CHAR_ID)
        world = _world("门派乙", wid=WORLD_ID)
        mock_character_repo.get = AsyncMock(return_value=char)
        mock_character_repo.list_all = AsyncMock(return_value=[char])
        mock_world_repo.get = AsyncMock(return_value=world)
        mock_world_repo.list_all = AsyncMock(return_value=[world])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[
                _kr(
                    source_id=CHAR_ID,
                    target_id=WORLD_ID,
                    relation_type="属于",
                    description="出身地",
                )
            ]
        )

        xml, filename = await svc.export_mxgraph(PID)

        assert 'label="属于"' in xml
        assert f'id="character:{CHAR_ID}"' in xml
        assert f'id="world:{WORLD_ID}"' in xml
        assert filename == "项目甲-knowledge-graph.drawio"

    @pytest.mark.asyncio
    async def test_export_is_byte_identical_across_two_calls(
        self, svc, mock_relation_repo, mock_character_repo
    ) -> None:
        char = _char("角色甲", cid=CHAR_ID)
        mock_character_repo.list_all = AsyncMock(return_value=[char])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[_kr(source_id=CHAR_ID, target_id=CHAR_ID, relation_type="自指")]
        )
        first, _ = await svc.export_mxgraph(PID)
        second, _ = await svc.export_mxgraph(PID)
        assert first == second

    @pytest.mark.asyncio
    async def test_export_skips_edge_with_missing_endpoint(
        self, svc, mock_relation_repo, mock_character_repo
    ) -> None:
        """关系指向已删实体 → 跳过 + 不抛（不生成悬空引用）。"""
        mock_character_repo.list_all = AsyncMock(return_value=[])
        mock_relation_repo.list_by_project = AsyncMock(
            return_value=[_kr(source_id=CHAR_ID, target_id=WORLD_ID, relation_type="师承")]
        )
        xml, _ = await svc.export_mxgraph(PID)
        assert "kr:" not in xml

    @pytest.mark.asyncio
    async def test_export_without_relations_is_empty_graph(self, svc, mock_relation_repo) -> None:
        mock_relation_repo.list_by_project = AsyncMock(return_value=[])
        xml, _ = await svc.export_mxgraph(PID)
        assert _mxgraph_codec.parse_mxgraph_xml(xml) == []


class TestImportMxgraph:
    """service.import_mxgraph(project_id, xml, mode)。"""

    @pytest.mark.asyncio
    async def test_import_invalid_xml_raises_and_writes_nothing(
        self, svc, mock_relation_repo
    ) -> None:
        with pytest.raises(MxGraphImportError):
            await svc.import_mxgraph(PID, "<mxfile><diagram></mxfile>")
        mock_relation_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_parse_failure_does_not_delete_on_replace(
        self, svc, mock_relation_repo
    ) -> None:
        with pytest.raises(MxGraphImportError):
            await svc.import_mxgraph(PID, "<foo/>", mode="replace")
        mock_relation_repo.delete_by_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_new_edge_succeeds_and_counts(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        char = _char("角色甲", cid=CHAR_ID)
        world = _world("门派乙", wid=WORLD_ID)
        mock_character_repo.get = AsyncMock(return_value=char)
        mock_world_repo.get = AsyncMock(return_value=world)
        xml = _wrap(
            _node_cell(f"character:{CHAR_ID}", "角色甲"),
            _node_cell(f"world:{WORLD_ID}", "门派乙"),
            _edge_cell(
                "kr:k1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}", tooltip="出身地"
            ),
        )

        result = await svc.import_mxgraph(PID, xml, mode="merge")

        assert (result.mode, result.total, result.imported) == ("merge", 1, 1)
        assert (result.skipped, result.failed, result.deleted) == (0, 0, 0)
        assert result.details == []
        mock_relation_repo.add.assert_awaited()

    @pytest.mark.asyncio
    async def test_import_conflict_skipped_and_reported(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(return_value=_char("角色甲", cid=CHAR_ID))
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        mock_relation_repo.get_by_key = AsyncMock(
            return_value=_kr(source_id=CHAR_ID, target_id=WORLD_ID, relation_type="属于")
        )
        xml = _wrap(_edge_cell("kr:k1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"))

        result = await svc.import_mxgraph(PID, xml, mode="merge")

        assert (result.imported, result.skipped, result.failed) == (0, 1, 0)
        assert result.details[0].kind == "skipped"
        assert "已存在" in result.details[0].reason
        mock_relation_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_self_loop_counts_failed_without_aborting(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(return_value=_char("角色甲", cid=CHAR_ID))
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        xml = _wrap(
            _edge_cell("kr:loop", "自指", f"character:{CHAR_ID}", f"character:{CHAR_ID}"),
            _edge_cell("kr:ok", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"),
        )

        result = await svc.import_mxgraph(PID, xml, mode="merge")

        assert (result.total, result.imported, result.failed) == (2, 1, 1)
        assert result.details[0].kind == "failed"
        assert "自环" in result.details[0].reason

    @pytest.mark.asyncio
    async def test_import_unresolvable_endpoint_counts_failed(
        self, svc, mock_relation_repo
    ) -> None:
        xml = _wrap(_edge_cell("kr:x", "师承", "X1a2b3c", f"world:{WORLD_ID}"))
        result = await svc.import_mxgraph(PID, xml, mode="merge")
        assert (result.imported, result.failed) == (0, 1)
        assert "端点无法解析" in result.details[0].reason
        mock_relation_repo.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_cross_project_entity_counts_failed(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(
            return_value=_char("外来者", project_id=PID_OTHER, cid=CHAR_ID)
        )
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        xml = _wrap(_edge_cell("kr:x", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"))

        result = await svc.import_mxgraph(PID, xml, mode="merge")

        assert (result.imported, result.failed) == (0, 1)
        assert "同一项目" in result.details[0].reason

    @pytest.mark.asyncio
    async def test_import_counts_identity_holds(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(return_value=_char("角色甲", cid=CHAR_ID))
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        mock_relation_repo.get_by_key = AsyncMock(
            side_effect=lambda *a, **k: _kr(
                source_id=CHAR_ID, target_id=WORLD_ID, relation_type="属于"
            )
        )
        xml = _wrap(
            _edge_cell("kr:1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"),
            _edge_cell("kr:2", "自指", f"character:{CHAR_ID}", f"character:{CHAR_ID}"),
            _edge_cell("kr:3", "师承", "X1a2b3c", f"world:{WORLD_ID}"),
        )
        result = await svc.import_mxgraph(PID, xml, mode="merge")
        assert result.total == result.imported + result.skipped + result.failed == 3

    @pytest.mark.asyncio
    async def test_import_replace_deletes_before_insert(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(return_value=_char("角色甲", cid=CHAR_ID))
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        mock_relation_repo.delete_by_project = AsyncMock(return_value=2)
        xml = _wrap(_edge_cell("kr:1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"))

        result = await svc.import_mxgraph(PID, xml, mode="replace")

        assert (result.mode, result.deleted, result.imported) == ("replace", 2, 1)
        mock_relation_repo.delete_by_project.assert_awaited_once_with(PID)

    @pytest.mark.asyncio
    async def test_import_merge_keeps_existing_rows(
        self, svc, mock_relation_repo, mock_character_repo, mock_world_repo
    ) -> None:
        mock_character_repo.get = AsyncMock(return_value=_char("角色甲", cid=CHAR_ID))
        mock_world_repo.get = AsyncMock(return_value=_world("门派乙", wid=WORLD_ID))
        xml = _wrap(_edge_cell("kr:1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"))
        result = await svc.import_mxgraph(PID, xml)
        assert result.deleted == 0
        mock_relation_repo.delete_by_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_missing_project_raises_not_found(self, svc, mock_project_repo) -> None:
        mock_project_repo.get = AsyncMock(return_value=None)
        xml = _wrap(_edge_cell("kr:1", "属于", f"character:{CHAR_ID}", f"world:{WORLD_ID}"))
        with pytest.raises(ProjectNotFoundError):
            await svc.import_mxgraph(PID, xml, mode="merge")
