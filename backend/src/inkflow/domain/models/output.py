"""F21 导出服务领域模型 — 导出 DTO 与格式枚举（spec §2）.

本模块只定义导出管线的「瞬态中间表示」与「传输 DTO」：
- BookDocument（统一中间表示）: 聚合层把项目正文（卷/章）与设定档案
  （角色/世界观/大纲/时间线/伏笔）组装为单一文档树，序列化器只消费它。
- ExportRequest / ExportResult: API query / CLI 选项与 CLI --json 信封的
  统一语义（spec §2.3）。

F21 不新建持久化实体（无新表、无迁移）——所有输入来自既有模块实体，
本模块全部为瞬态计算产物（spec §1 边界声明 / §2 决策论证表）。

依据: specs/f21-export/spec.md §2。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ExportFormat(StrEnum):
    """导出格式（v1.1 拍板：仅 TXT）。"""

    TXT = "txt"


class BookMeta(BaseModel):
    """项目元信息（导出文件头部使用）.

    Attributes:
        title: 书名（project.name）.
        genre: 类型中文字面量（" ".join(project.tags)）.
        language: 写作语言（默认 zh-CN）.
        target_words: 目标字数.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    title: str
    genre: str
    language: str
    target_words: int
    updated_at: datetime


class BookChapter(BaseModel):
    """单章（正文树节点）.

    Attributes:
        title: 章标题.
        content: 原样正文（含换行），不做格式清洗.
        order_index: 卷内排序键.
        word_count: 展示用字数.
    """

    model_config = {"from_attributes": True}

    title: str
    content: str
    order_index: float
    word_count: int


class BookVolume(BaseModel):
    """卷（正文树一层；无卷章节挂 volume_id=None 的「未分组」卷下）.

    Attributes:
        title: 卷标题（可空，序列化时「第 X 卷」占位）.
        order_index: 排序键.
        chapters: 卷内章节列表（必填；调用方显式传空列表表示空卷）.
    """

    model_config = {"from_attributes": True}

    title: str
    order_index: float
    chapters: list[BookChapter]


class BookSetting(BaseModel):
    """设定档案条目（附录；type 对应各模块）.

    Attributes:
        type: character / world / outline / timeline / foreshadowing.
        name: 条目名（角色名/条目名/大纲名/事件标题/伏笔名）.
        content: 各模块摘要拼接（spec §6.3）.
    """

    model_config = {"from_attributes": True}

    type: str
    name: str
    content: str


class BookDocument(BaseModel):
    """统一中间表示（聚合输出，序列化器唯一输入）.

    Attributes:
        meta: 项目元信息.
        volumes: 正文卷树（无卷章节在「未分组」卷）.
        settings: 设定档案附录（include_settings=False 时为空列表）.
    """

    model_config = {"from_attributes": True}

    meta: BookMeta
    volumes: list[BookVolume] = Field(default_factory=list)
    settings: list[BookSetting] = Field(default_factory=list)


class ExportRequest(BaseModel):
    """导出参数（API query / CLI 选项统一语义）.

    Attributes:
        format: 导出格式（v1.1 唯一值 txt）.
        include_settings: 是否含设定档案附录（Q3=C 拍板默认不含）.
    """

    format: ExportFormat = ExportFormat.TXT
    include_settings: bool = False


class ExportResult(BaseModel):
    """CLI --json 信封的 payload（API 直接返回字节流，不用此模型）.

    Attributes:
        format: 导出格式.
        filename: 建议文件名（含 .txt 扩展名）.
        bytes: 字节数.
        path: CLI 实际写入路径（API 侧为空）.
    """

    format: ExportFormat
    filename: str
    bytes: int
    path: str
