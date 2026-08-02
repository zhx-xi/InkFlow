"""F16 风格检测服务编排（spec §5.1/§5.7/§8.1）— 只读文本分析.

StyleService 是 F16 的编排核心: 构造注入 F1 ProjectRepositoryProtocol /
F2 ChapterRepositoryProtocol 与可选 LLM 深度分析器（StyleLLMAnalyzer | None，
Q1=C），analyze 按 spec §5.1 步骤 ①-⑥ 执行:

① 项目校验（project_repo.get → None → ProjectNotFoundError 404——先于输入校验）
② 输入源解析（text 模式 strip 去空白校验；chapter_ids 模式逐章读取——
   不存在 → ChapterNotFoundError、跨项目 → ChapterNotInProjectError、
   内容超 50000 → StyleValidationError；多章按请求顺序合并，章间 "\\n\\n"）
③④⑤ 纯函数分析（_style_analyzer 模块级函数: 一次预处理 + token 化共享
   快照 → 风格指纹 / AI 痕迹 / 词汇分析三板块）→ 组装 StyleReport + warnings
⑥ LLM 深度分析（可选，Q1=C）: llm_analysis 三级判定（请求显式 →
   项目配置 extra["style_llm_analysis"] → 默认 false）→ true 时调用
   StyleLLMAnalyzer 注入 llm_assessment；分析器未装配 → StyleLLMUnavailableError

算法全部在 _style_analyzer.py 纯函数层（spec §5.2-§5.5），本类只做编排；
只依赖 domain/ports/ 与 domain/models/，不依赖任何 infrastructure 实现——
domain/ 零框架 import 门禁天然满足（ADR-002/015）。

依据: specs/f16-style-service/spec.md §5.1/§5.7/§7/§8.1/§9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from inkflow.domain.models.project import Project
from inkflow.domain.models.style import StyleReport
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError, ChapterNotInProjectError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.style_errors import StyleLLMUnavailableError, StyleValidationError
from inkflow.domain.services._style_analyzer import (
    _analyze,
    _analyze_ai_trace,
    _analyze_fingerprint,
    _analyze_lexical,
)

if TYPE_CHECKING:
    from inkflow.domain.services._style_llm_analyzer import StyleLLMAnalyzer

_MAX_CHAPTER_CHARS = 50000
"""章节内容分析上限（spec §3.3/§7: 超 50000 字符 → StyleValidationError 422）。"""


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1/F14/F15 `_to_int_id` 模式）.

    Args:
        value: 领域 UUID 或已有 int 主键.

    Returns:
        仓储层 int 主键（UUID 取其 int 表示）.
    """
    if isinstance(value, uuid.UUID):
        return value.int
    return value


def _resolve_llm_analysis(llm_analysis: bool | None, project: Project) -> bool:
    """LLM 深度分析三级判定（spec §2.8/§5.1 要点 8）.

    优先级: 请求显式 llm_analysis → 项目配置 extra["style_llm_analysis"] →
    默认 false（AI 自动化默认关闭——LLM 深度分析仅用户显式开启才调用）。

    Args:
        llm_analysis: 请求开关（None = 跟随项目配置）.
        project: 已校验的所属项目（config.extra 读取项目级设置）.

    Returns:
        True = 本次分析应调用 LLM 深度分析器.
    """
    if llm_analysis is not None:
        return llm_analysis
    return bool(project.config.extra.get("style_llm_analysis", False))


class StyleService:
    """风格检测服务（spec §5）— 只读文本分析编排.

    依赖全部通过构造函数注入（ADR-015/ADR-009，测试注入 Mock）:

    Args:
        project_repo: F1 项目仓储——get 项目校验（§5.1 步骤 ①，404 语义）.
        chapter_repo: F2 章节仓储——get_chapter 章节读取（chapter_ids 模式，
            不存在/跨项目/超长校验，§5.1 步骤 ②）.
        llm_analyzer: LLM 深度分析器（Q1=C，可选装配）——仅 llm_analysis=true
            时调用；None = 未装配 → llm_analysis=true 抛 StyleLLMUnavailableError
            （§5.6/§7，镜像 F14 RAGUnavailableError 语义）.

    只依赖 domain/ports/ 与 domain/models/（Protocol 与纯 Pydantic 模型），
    不依赖任何 infrastructure 实现——domain/ 零框架 import 门禁天然满足
    （ADR-002/015）。算法全部在 _style_analyzer.py 纯函数层（§5.2-§5.5），
    本类无算法逻辑。
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        llm_analyzer: StyleLLMAnalyzer | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._llm_analyzer = llm_analyzer

    # ── 服务编排（spec §5.1 步骤 ①-⑥）────────────────────────────

    async def analyze(
        self,
        project_id: uuid.UUID,
        *,
        text: str | None = None,
        chapter_ids: list[uuid.UUID] | None = None,
        llm_analysis: bool | None = None,
    ) -> StyleReport:
        """风格分析编排（spec §5.1 步骤 ①-⑥）.

        流程: 项目校验（先于输入校验）→ 输入源解析（text 模式 / 章节模式
        逐章读取校验 + 按请求顺序合并）→ 纯函数三块分析（共享同一统计快照）
        → 组装 StyleReport（source/generated_at/warnings）→ LLM 深度分析
        （可选，三级判定）。只读幂等：同一输入两次分析报告逐字段相等（除
        generated_at，§6.4）；任一仓储读取失败即抛异常透传，不产出部分报告
        （§5.1 要点 6）。

        Args:
            project_id: 所属项目 UUID.
            text: 手动文本（与 chapter_ids 互斥，strip 后非空）.
            chapter_ids: 章节模式（F2 读取，按请求顺序合并为整体分析，
                章间 "\\n\\n" 分隔）.
            llm_analysis: LLM 深度分析开关（Q1=C，§2.8）——None = 跟随项目
                配置 extra["style_llm_analysis"]（默认 false）.

        Returns:
            StyleReport（source 标记 manual/chapter:<id>/chapters:<ids>，
            §2.6；含可选 llm_assessment 板块，§2.7）.

        Raises:
            ProjectNotFoundError: 项目不存在（404）.
            StyleValidationError: 输入校验失败（互斥/缺失/空文本/章节超长，422）.
            ChapterNotFoundError / ChapterNotInProjectError: 章节校验失败
                （422，F14 错误类）.
            StyleLLMUnavailableError: llm_analysis=true 且分析器未装配（500，§5.6）.
        """
        # ① 项目校验（服务层统一校验一次，404；先于输入校验，§5.1 要点 2）
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

        # ② 输入校验（text 与 chapter_ids 互斥 / 必填其一，§5.1 要点 4）
        if text is not None and chapter_ids is not None:
            raise StyleValidationError("text 与 chapter_ids 不能同时使用")
        if text is None and chapter_ids is None:
            raise StyleValidationError("必须提供 text 或 chapter_ids")

        # ② 输入源解析（text 模式: strip 去空白校验，§5.7）
        if text is not None:
            stripped = text.strip()
            if not stripped:
                raise StyleValidationError("文本不能为空")
            clean_text = stripped
            source = "manual"
        else:
            # ② 输入源解析（章节模式: 逐章读取 + 校验 + 按请求顺序合并，§5.1 要点 5）
            ids = chapter_ids or []
            chunks: list[str] = []
            for cid in ids:
                chapter = await self._chapter_repo.get_chapter(_to_int_id(cid))
                if chapter is None:
                    raise ChapterNotFoundError()  # F2 get 不含软删
                if chapter.project_id != project_id:
                    raise ChapterNotInProjectError()
                if len(chapter.content) > _MAX_CHAPTER_CHARS:
                    raise StyleValidationError("章节内容超过分析上限（50000 字符）")
                chunks.append(chapter.content)
            clean_text = "\n\n".join(chunks)  # 章间 "\\n\\n" 分隔（避免章节边界句粘连）
            source = (
                f"chapter:{ids[0]}"
                if len(ids) == 1
                else f"chapters:{','.join(str(i) for i in ids)}"
            )

        # ③④⑤ 预处理 + 三块分析 + 组装（§5.2-§5.5，全部纯函数共享同一快照）
        stats = _analyze(clean_text)
        warnings: list[str] = []
        if len(chapter_ids or []) > 1:
            warnings.append("多章节合并分析（单章粒度分析归 Phase 2+）")
        if stats.sentence_count == 0:
            warnings.append("未检测到完整句子（句尾符不足）——句子统计仅供参考")
        if stats.total_words == 0:
            warnings.append("文本无有效词条（仅标点/空白）——词汇统计为空")
        report = StyleReport(
            project_id=project_id,
            source=source,
            generated_at=datetime.now(UTC),
            fingerprint=_analyze_fingerprint(stats),
            ai_trace=_analyze_ai_trace(stats),
            lexical=_analyze_lexical(stats),
            warnings=warnings,
        )

        # ⑥ LLM 深度分析（可选，Q1=C）——三级判定 + 注入 llm_assessment（§5.6）
        if _resolve_llm_analysis(llm_analysis, project):
            if self._llm_analyzer is None:
                raise StyleLLMUnavailableError("LLM 深度分析不可用")
            report.llm_assessment = await self._llm_analyzer.analyze(
                project=project, text=clean_text
            )
        return report
