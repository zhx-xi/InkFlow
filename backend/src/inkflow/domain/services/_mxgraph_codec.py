"""F48 drawio（mxGraph XML）编解码器 — 纯函数、仅标准库（spec §5.7.1）.

设计约束（AGENTS.md §4.2 + ADR-061）:
- 只依赖标准库 ``xml.etree.ElementTree`` / ``uuid``；domain 层零框架依赖
- 纯函数、零随机、零时间戳：同输入两次调用输出**逐字节一致**（往返幂等前提）
- 交换格式只表达「参与至少一条关系的实体 + 关系边」，不承载实体清单/排版态

节点 id 恒 ``<entity_type>:<entity_uuid>``（与 GraphNode.id 同构），边 id 恒
``kr:<relation_uuid>``（GraphEdge.id 原样回写）——两者是导入解析的唯一锚点。

依据: specs/f48-knowledge-graph/spec.md §5.7.1/§5.7.3；ADR-061。
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from inkflow.domain.models.knowledge_graph import EntityType, GraphEdge, GraphNode, MxGraphEdge
from inkflow.domain.ports.knowledge_graph_errors import MxGraphImportError

MXGRAPH_FORMAT: str = "mxgraph"
"""交换格式标识（端点 ``?format=`` 唯一取值，spec §5.7.2）。"""

_DIAGRAM_NAME = "知识图谱"
"""``<diagram name>`` 固定值（drawio 侧显示名，spec §5.7.1 示例）。"""

_ROOT_TAGS = {"mxfile", "mxGraphModel"}
"""合法根元素（其余 → MxGraphImportError，spec §5.7.3 解析规则 1）。"""

_WRAPPER_TAGS = {"object", "UserObject"}
"""drawio 自定义元数据包装元素（label/tooltip 载体，spec §5.7.1）。"""

_NODE_TYPE_ORDER: tuple[EntityType, ...] = (
    EntityType.CHARACTER,
    EntityType.WORLD,
    EntityType.OUTLINE,
    EntityType.TIMELINE,
    EntityType.FORESHADOW,
    EntityType.MAP_PIN,
)
"""节点类型列序（col = index，spec §5.7.1 确定性网格）。"""

_NODE_STYLE: dict[EntityType, tuple[str, str]] = {
    EntityType.CHARACTER: ("#e8f0fe", "#4a7ebb"),
    EntityType.WORLD: ("#e6f4ea", "#4c9a6a"),
    EntityType.OUTLINE: ("#fef7e0", "#c2a12e"),
    EntityType.TIMELINE: ("#f3e8fd", "#8a5fbe"),
    EntityType.FORESHADOW: ("#fde8e8", "#c05a5a"),
    EntityType.MAP_PIN: ("#e8fbfb", "#3d9a9a"),
}
"""节点朴素 mxCell 配色（仅服务 drawio 排版，导入不读，spec §5.7.1）。"""

_ILLEGAL_FILENAME_CHARS = '\\/:*?"<>|'
"""Windows 文件名禁符（逐字符替换为 ``_``，spec §5.7.1 文件名规则）。"""

_MAX_NAME_CHARS = 60
"""书名截断长度（spec §5.7.1）。"""


def build_mxgraph_xml(nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    """GraphNode/GraphEdge 列表 → mxGraph XML 文本（drawio 桌面版可原样打开）.

    Args:
        nodes: 节点（调用方已按图谱节点序排好；本函数按给定顺序计算网格行号）.
        edges: 边（id 恒 ``kr:<uuid>``，原样写入 ``<object id>``）.

    Returns:
        无 XML 声明的 mxGraph XML 字符串；同输入两次调用逐字节一致.
    """
    mxfile = ET.Element("mxfile", {"host": "InkFlow", "type": "device"})
    diagram = ET.SubElement(
        mxfile, "diagram", {"id": "inkflow-knowledge-graph", "name": _DIAGRAM_NAME}
    )
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "800",
            "dy": "600",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "850",
            "pageHeight": "1100",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    rows: dict[EntityType, int] = {}
    for node in nodes:
        col = _NODE_TYPE_ORDER.index(node.type)
        row = rows.get(node.type, 0)
        rows[node.type] = row + 1
        fill, stroke = _NODE_STYLE.get(node.type, ("#ffffff", "#666666"))
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"{node.type.value}:{node.entity_id}",
                "value": node.name,
                "style": f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};",
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(40 + col * 200),
                "y": str(40 + row * 60),
                "width": "140",
                "height": "40",
                "as": "geometry",
            },
        )

    for edge in edges:
        attrs = {"id": edge.id, "label": edge.label}
        if edge.description:
            attrs["tooltip"] = edge.description
        wrapper = ET.SubElement(root, "object", attrs)
        cell = ET.SubElement(
            wrapper,
            "mxCell",
            {
                "style": "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;",
                "edge": "1",
                "parent": "1",
                "source": edge.source,
                "target": edge.target,
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.tostring(mxfile, encoding="unicode")


def _localname(tag: object) -> str:
    """去 XML 命名空间前缀（``{ns}mxCell`` → ``mxCell``）."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_mxgraph_xml(xml: str) -> list[MxGraphEdge]:
    """mxGraph XML 文本 → 边 cell 列表（文档序；端点为原始 cell id，不解析）.

    Args:
        xml: drawio 文件内容（``<mxfile>`` 或裸 ``<mxGraphModel>`` 均可）.

    Returns:
        文档序的 MxGraphEdge 列表；顶点/结构 cell 忽略.

    Raises:
        MxGraphImportError: 非法 XML / 根元素不是 mxfile|mxGraphModel /
            找不到 mxGraphModel / 输入为空.
    """
    if xml.strip() == "":
        raise MxGraphImportError("非法 mxGraph XML：输入为空")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise MxGraphImportError(f"非法 mxGraph XML：无法解析（{exc}）") from exc
    if _localname(root.tag) not in _ROOT_TAGS:
        raise MxGraphImportError(f"非法 mxGraph XML：根元素不是 mxfile（{_localname(root.tag)}）")

    model = None
    if _localname(root.tag) == "mxGraphModel":
        model = root
    else:
        for element in root.iter():
            if _localname(element.tag) == "mxGraphModel":
                model = element
                break
    if model is None:
        if _localname(root.tag) == "mxfile":
            for element in root.iter():
                if _localname(element.tag) == "diagram" and (element.text or "").strip():
                    raise MxGraphImportError(
                        "非法 mxGraph XML：疑似被 drawio 压缩保存"
                        "（导出为 XML 时勾选了 Compressed），请取消压缩后重存"
                    )
        raise MxGraphImportError("非法 mxGraph XML：缺少 mxGraphModel 元素")

    parents: dict[ET.Element, ET.Element] = {}
    for parent in model.iter():
        for child in parent:
            parents[child] = parent

    edges: list[MxGraphEdge] = []
    for cell in model.iter():
        if _localname(cell.tag) != "mxCell":
            continue
        has_endpoints = cell.get("source") is not None and cell.get("target") is not None
        if cell.get("edge") != "1" and not has_endpoints:
            continue
        wrapper = parents.get(cell)
        if wrapper is not None and _localname(wrapper.tag) in _WRAPPER_TAGS:
            cell_id = wrapper.get("id") or cell.get("id") or ""
            label = wrapper.get("label")
            if label is None:
                label = cell.get("value") or ""
            description = wrapper.get("tooltip") or ""
        else:
            cell_id = cell.get("id") or ""
            label = cell.get("value") or ""
            description = ""
        edges.append(
            MxGraphEdge(
                id=cell_id,
                label=label,
                description=description,
                source=cell.get("source") or "",
                target=cell.get("target") or "",
            )
        )
    return edges


def parse_entity_ref(cell_id: str) -> tuple[EntityType, uuid.UUID] | None:
    """cell id → ``(EntityType, uuid.UUID)``；非法引用返回 None.

    按**第一个** ``:`` 拆分为 ``<type>`` / ``<uuid>``；type 必须 ∈ EntityType 六值、
    uuid 必须可解析，否则 None（手工在 drawio 新画的节点即属此类）.
    """
    if ":" not in cell_id:
        return None
    type_str, uuid_str = cell_id.split(":", 1)
    try:
        entity_type = EntityType(type_str)
    except ValueError:
        return None
    try:
        entity_id = uuid.UUID(uuid_str)
    except (ValueError, AttributeError, TypeError):
        return None
    return entity_type, entity_id


def suggest_drawio_filename(project_name: str) -> str:
    """书名 → drawio 文件名建议（清洗 Windows 禁符 + 截断 60 字符 + 固定后缀）."""
    cleaned = project_name.strip()
    if not cleaned:
        cleaned = "untitled"
    for char in _ILLEGAL_FILENAME_CHARS:
        cleaned = cleaned.replace(char, "_")
    cleaned = cleaned[:_MAX_NAME_CHARS]
    return f"{cleaned}-knowledge-graph.drawio"
