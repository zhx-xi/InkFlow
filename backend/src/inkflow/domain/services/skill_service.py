"""Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

职责（spec §2.2/§3.3/§5.6/§7 + ADR-039 #522）:
- 文件系统真源：skill 实体 = data_dir/skills/<name>/SKILL.md（不再落 DB
  表）；list 扫描 skills_root/*/SKILL.md，get/create/update/delete/
  duplicate 全部内联文件系统操作（不再注入 skill_repository）
- frontmatter 后端解析（422）：create/update(content) 复用
  inkflow.cli.skills_parser.parse_skill_metadata（N2 严格规则
  ^[a-z0-9]+(-[a-z0-9]+)*$，name 须=目录名）；失败 → SkillFrontmatterError
- 同名唯一性校验（422）：create/duplicate 前检查同名目录已存在 →
  SkillNameConflictError
- 资源不存在（404 语义）：get/update/delete/duplicate 目标缺失 →
  SkillNotFoundError
- source 判定：目录名 ∈ BUILTIN_SKILL_NAMES（6 英文 slug）→ "builtin"
  （只读 409），否则 "user_upload"
- delete：source="builtin" → SkillBuiltinError（409）；被 N 个 Agent
  引用 → 先级联清引用（逐个移除 Agent.skill_ids 中的该目录名并
  agent_repository.update）再删目录（spec §5.6）
- 时间戳契约：created_at/updated_at 为 SKILL.md 文件 mtime ISO 字符串
  （create/update 写盘后读取；不锁精确值）

依赖通过构造函数注入（ADR-015，测试注入 Mock）；文件系统操作内联实现。
"""

from __future__ import annotations

import builtins
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.cli.skills_parser import SkillMetadata, SkillValidationError, parse_skill_metadata
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.services._data_change import publish_change

logger = logging.getLogger(__name__)


BUILTIN_SKILL_NAMES: list[str] = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 出厂目录名（英文 slug，N2 合规；顺序 = ensure_builtin_skills 写出序）."""


class _BuiltinSkillSpec(TypedDict):
    """内置 Skill 出厂配置项（spec §5.3，content = 完整 SKILL.md）."""

    name: str
    description: str
    content: str


BUILTIN_SKILL_SPECS: list[_BuiltinSkillSpec] = [
    {
        "name": "architecture-methodology",
        "description": "章节结构/大纲规划方法论",
        "content": (
            "---\n"
            "name: architecture-methodology\n"
            "description: 章节结构/大纲规划方法论\n"
            "---\n"
            "\n"
            "# 架构方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于在撰写正文之前规划章节结构与大纲，确保目标章节在全书弧线中\n"
            "的位置清晰、起承转合完整，并与既有伏笔、角色设定和世界观设定保持一致。\n"
            "适用于新建章节规划、章节拆分合并以及大纲调整场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **定位层级**：先判断本次规划对象是整本根 / 卷纲 / 章纲 / 情节点中的\n"
            "   哪一层，再决定颗粒度。总纲缺位时先补最小可用骨架，不要跳过上游直接写章纲。\n"
            "2. **确认位置**：读取前文摘要，判断本章处于全书弧线的开端、发展、高潮还是\n"
            "   收束阶段，据此决定本章节奏与篇幅，避免出现连续三个同强度章节。\n"
            "3. **核对伏笔账**：逐条检查既有伏笔的埋设章与计划回收章，确认本章是否有\n"
            "   应收未收的伏笔；新埋的伏笔必须写明「计划在第几章回收」与「回收线索物」。\n"
            "4. **核对设定边界**：本章新情节是否越出角色能力上限或世界观规则；\n"
            "   与既有档案冲突时改规划而不是改设定（设定改动须回到设定流程）。\n"
            "5. **校对时间线**：确认本章在项目时间轴上的位置与前章连续，\n"
            "   跨场景时间跳跃须在规划里写明跨度，防止后文时序穿帮。\n"
            "6. **规划章节骨架**：按起承转合组织，明确冲突推进与情绪转折，\n"
            "   确定悬念埋设与伏笔回收计划，保证章节节奏张弛有度。\n"
            "7. **输出结构化规划**：章节目标 / 场景清单 / 关键事件 / 伏笔操作 / 衔接要点。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不直接撰写正文：本 skill 只产出章节规划，正文由写作方法论负责。\n"
            "- 不落库：架构师只有大纲只读权限，规划以文本形式交付，落库由用户确认后执行。\n"
            "- 不擅自新增角色或世界观设定：超出既有档案的内容标注为待确认项，交由用户决策。\n"
            "- 避免规划过度具体：场景描写与对话台词留给正文阶段，此处只锁定结构、冲突与伏笔走向。\n"
            "- 不制造「空转折」：每一处转折必须写明由什么事件触发、改变谁的处境，\n"
            "  只写「气氛突变」而不给因果的规划视为未完成。\n"
            "\n"
            "## 示例\n"
            "\n"
            "规划「第 12 章」：先确认层级=章纲、本章位于发展段转折点；读取前文摘要与\n"
            "时间轴确认紧接第 11 章当夜；核对伏笔账发现第 3 章埋设的信物计划在第 12 章\n"
            "回收；核对角色设定确认主角当前能力上限不支持正面冲突，故规划为智取。\n"
            "输出——章目标：回收信物伏笔并引出下一冲突；场景清单：旧宅搜查 → 信件发现\n"
            "→ 对峙；伏笔操作：回收信物、新埋「账册缺页」；衔接：章末留下账册缺页线索。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "规划交付前逐条确认，任一条不满足则补完再交：\n"
            "\n"
            "- [ ] 层级明确：本次产出挂在哪一层（整本根 / 卷纲 / 章纲 / 情节点），父级是谁\n"
            "- [ ] 位置明确：本章在全书弧线的哪个阶段，上一章与下一章的衔接点各是什么\n"
            "- [ ] 因果闭合：每个关键事件都由前一事件触发，每处转折都写明触发者与被改变者\n"
            "- [ ] 伏笔两清：本章要埋的（含计划回收章 + 线索物）与要收的（含埋设章）均已列出\n"
            "- [ ] 设定无越界：新情节未越过角色能力上限与世界观规则，冲突项已标为待确认\n"
            "- [ ] 时序连续：本章在项目时间轴上的位置明确，跨场景跳跃已写明跨度\n"
            "- [ ] 无空转折：不存在只写「气氛突变」而无因果的段落\n"
            "\n"
            "## 与其他方法论的衔接\n"
            "\n"
            "| 阶段 | 负责 skill | 交接物 |\n"
            "|------|-----------|--------|\n"
            "| 结构规划（本 skill） | architecture-methodology | 章纲（目标/场景/事件/伏笔） |\n"
            "| 正文落地 | writing-methodology | 按章纲产出草稿 |\n"
            "| 质量把关 | audit-methodology | findings 清单 |\n"
            "| 设定把关 | worldview-methodology | 世界观冲突建议 |\n"
            "| 问题落地 | revision-methodology | 修订稿 |\n"
            "| 文笔收尾 | polishing-methodology | 润色稿 |\n"
            "\n"
            "本 skill 位于链路最上游：章纲未确认时，下游全部环节的结果都不可靠，\n"
            "因此宁可多花时间在规划阶段，也不要带着结构问题进入写作。\n"
        ),
    },
    {
        "name": "writing-methodology",
        "description": "正文生成方法论",
        "content": (
            "---\n"
            "name: writing-methodology\n"
            "description: 正文生成方法论\n"
            "---\n"
            "\n"
            "# 写作方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于按既定大纲撰写章节正文，将规划落地为可读的小说文本，要求\n"
            "场景切换自然、对话符合人设、视角保持一致，并在完成后保存草稿。适用于\n"
            "大纲已确认、需要产出正文初稿的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **读大纲**：先读本章章纲（目标 / 场景清单 / 关键事件 / 伏笔操作），\n"
            "   再获取前文摘要保持衔接。大纲未确认时先回到架构方法论，不要边写边改结构。\n"
            "2. **建设定卡**：动笔前把本章出场角色与涉及的世界观条目读出来，\n"
            "   把关键约束抄成一张临时对照卡（称呼 / 能力上限 / 禁忌 / 已确立事实）。\n"
            "3. **按场景推进**：每个场景一段推进，场景切换用过渡句自然衔接，避免跳切生硬。\n"
            "4. **对话查档案**：对照角色档案确认语气、称呼与禁忌符合人设，全程保持统一视角\n"
            "   （人称、限知范围不跳变）。\n"
            "5. **写时查证不猜**：遇到设定细节先查设定库；查不到就留白或写待确认标记，\n"
            "   不得凭印象编造——凭空补设定是设定漂移的最大来源。\n"
            "6. **收尾自检**：对照大纲逐条确认关键事件落地、伏笔操作执行、\n"
            "   时间线与前章连续，然后保存草稿。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不擅自改变大纲结构：情节走向、关键事件与结局须遵循规划，需要调整先回到大纲规划。\n"
            "- 不引入与既有设定矛盾的信息：拿不准就留白，宁可欠一笔不可错一笔。\n"
            "- 不明确年份与时间锚点：时间以相对表述（三日后、同年秋）推进，\n"
            "  避免绝对年份造成的时序穿帮与后续不可改。\n"
            "- 不在草稿中插入审查性评论：审校、修订与润色由后续方法论负责。\n"
            "\n"
            "## 示例\n"
            "\n"
            "撰写「第 12 章」：读章纲确认三场景；建设定卡记录主角当前称呼、\n"
            "能力上限（不能正面冲突）、世界观禁忌（不可在旧宅点火）；\n"
            "按「旧宅搜查 → 信件发现 → 对峙」推进，对峙段用智取而非硬拼以符合能力上限；\n"
            "埋伏笔「账册缺页」时只留线索不解释；写完保存草稿并回执关键事件落地情况。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "草稿保存前逐条确认：\n"
            "\n"
            "- [ ] 大纲落地：章纲的关键事件逐条在正文中有对应段落，无漏写\n"
            "- [ ] 伏笔执行：本章应收的伏笔已回收，应收的线索已埋且未提前解释\n"
            "- [ ] 人设一致：每位出场角色的称呼、语气、能力表现均与档案相符\n"
            "- [ ] 视角稳定：全章人称与限知范围统一，无越界叙述\n"
            "- [ ] 设定无编造：所有设定细节均来自设定库，无凭印象新增\n"
            "- [ ] 时序连续：与前章的时间推进关系明确，全章未出现绝对年份\n"
            "- [ ] 无审查性文字：正文中不含点评、元叙述、待办标记\n"
            "\n"
            "## 对话写作要点\n"
            "\n"
            "对话是人设最容易露馅的地方，逐条对照：\n"
            "\n"
            "| 检查点 | 常见问题 | 修正方向 |\n"
            "|--------|----------|----------|\n"
            "| 称呼 | 不同场景下称呼跳变 | 按关系与场合选定，全章统一 |\n"
            "| 信息量 | 人物说出彼此都知道的事 | 只保留推动剧情的新信息 |\n"
            "| 语气 | 所有角色同一套腔调 | 按身份、教养、情绪区分措辞 |\n"
            "| 潜台词 | 把意图直接说破 | 留白，让行动与回避承担表达 |\n"
            "| 说话人 | 长对话中指向不明 | 交替处补动作或称呼锚定 |\n"
            "\n"
            "对话不宜承担设定讲解：确需交代设定时，让角色因剧情需要而说，\n"
            "而非为读者而说——「为读者而说」的对白一律改写或移入叙述。\n"
            "\n"
            "## 与其他方法论的衔接\n"
            "\n"
            "写作是「规划 → 文本」的唯一落地环节，输入必须已确认：\n"
            "\n"
            "| 输入 / 输出 | 来源 / 去向 | 说明 |\n"
            "|------------|------------|------|\n"
            "| 章纲（目标 / 场景 / 事件 / 伏笔） | 来自 architecture-methodology | 未确认则不写 |\n"
            "| 前文摘要 | 项目数据 | 保持衔接与文风连续 |\n"
            "| 角色档案 + 世界观条目 | 项目数据 | 建设定卡的来源 |\n"
            "| 草稿 | 交给 audit-methodology | 审计通过后才进入修订 |\n"
            "\n"
            "本 skill 只负责把规划变成可读文本，不负责判断规划对不对（上游）\n"
            "也不负责判断文本好不好（下游）。任一环节越位，责任边界即失效。\n"
        ),
    },
    {
        "name": "audit-methodology",
        "description": "一致性审计方法论",
        "content": (
            "---\n"
            "name: audit-methodology\n"
            "description: 一致性审计方法论\n"
            "---\n"
            "\n"
            "# 审校方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于对章节草稿执行一致性审计，检查字数、设定漂移与伏笔状态等\n"
            "方面的矛盾或遗漏，输出结构化 findings。适用于正文初稿完成、需要质量把关\n"
            "的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **统计体量**：先统计章节字数，确认是否符合目标篇幅，偏差过大时记为一条发现。\n"
            "2. **建证据链**：获取前文摘要与本章涉及的事件序列，把正文事实按发生顺序排列，\n"
            "   再与项目时间轴对照，找出顺序错位、跨度矛盾、同刻两地的时序问题。\n"
            "3. **查设定漂移**：逐条比对本章的角色档案与世界观设定——称呼、能力上限、\n"
            "   关系进展、世界观禁忌。凡正文出现档案里没有的能力/称谓/规则，即为漂移候选，\n"
            "   必须引用档案原文作为证据，不得凭印象判定。\n"
            "4. **核伏笔账**：对照伏笔清单检查本章应埋、应回收两项；漏埋与漏收分别成条，\n"
            "   并标注原计划章节号。\n"
            "5. **定级归类**：把每条发现按影响分级——阻断级（角色/设定硬冲突、时间线穿帮、\n"
            "   数据链断裂）、建议级（节奏、冗余）、存疑级（证据不足）。\n"
            "6. **输出结构化 findings**：逐条标注问题类型、位置、证据原文、影响级别与修改建议。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 只审计不改写：本 skill 产出问题清单，正文修改由修订方法论或写手完成。\n"
            "- 不臆断作者意图：证据不足的疑点标注为「存疑」而非直接判定错误；\n"
            "  尤其注意不得把作者的页面设定、后记、说明性文字当作正文缺陷。\n"
            "- 避免噪音式报错：重复问题合并为一条，聚焦影响读者理解的一致性缺陷。\n"
            "- 不越权下结论：审计只管「是否与既有设定冲突」，\n"
            "  「设定本身该不该改」由世界观顾问与用户裁决。\n"
            "\n"
            "## 示例\n"
            "\n"
            "审计「第 12 章」：字数超目标 2000 字（建议级）；时间线比对发现第 10 章记为\n"
            "「三日后」而本章称「次日」（阻断级，需回查上游）；设定比对发现主角称呼与前文\n"
            "不一致、且动用了档案未记载的能力（阻断级，设定漂移）；伏笔账发现第 3 章信物\n"
            "应本章回收却缺失（阻断级）。共 4 条 findings，每条含类型、位置、证据与建议。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "findings 交付前逐条确认：\n"
            "\n"
            "- [ ] 每条都有证据：引用原文片段与档案条目，不用「感觉不对」当依据\n"
            "- [ ] 每条都有位置：具体到段落或情节，可被定位复核\n"
            "- [ ] 每条都有分级：阻断级 / 建议级 / 存疑级，不混为一谈\n"
            "- [ ] 无重复条目：同一问题在不同位置不重复报\n"
            "- [ ] 未把作者侧文字当缺陷：后记 / 说明 / 待办标记不计入正文问题\n"
            "- [ ] 未越权判定设定：只报「与档案冲突」，不裁定「档案该改」\n"
            "- [ ] 覆盖四项：体量、时间线、设定漂移、伏笔账均已检查\n"
            "\n"
            "## 分级口径\n"
            "\n"
            "| 级别 | 判据 | 处理建议 |\n"
            "|------|------|----------|\n"
            "| 阻断级 | 角色/设定硬冲突、时间线穿帮、应收未收伏笔 | 必须处理后才可进入修订 |\n"
            "| 建议级 | 节奏拖沓、冗余重复、篇幅偏差 | 交用户决定是否本轮处理 |\n"
            "| 存疑级 | 证据不足或依赖作者意图 | 只提示，不要求修改 |\n"
            "\n"
            "分级是本 skill 的核心产出：把「一堆问题」变成「可排期的问题」，\n"
            "下游修订师据此决定改哪些、先改哪些。\n"
            "\n"
            "## 审计口径\n"
            "\n"
            "| 维度 | 查什么 | 证据来自 |\n"
            "|------|--------|----------|\n"
            "| 体量 | 字数是否达目标、章节间是否失衡 | 章节统计 + 目标篇幅 |\n"
            "| 时间线 | 事件顺序、时间跨度、同刻两地 | 前文摘要 + 项目时间轴 |\n"
            "| 设定漂移 | 称呼、能力上限、关系进展、世界观禁忌 | 角色档案 + 世界观条目 |\n"
            "| 伏笔账 | 应埋未埋、应收未收 | 伏笔清单 + 计划章节号 |\n"
            "| 叙事一致 | 视角跳变、人称混用、场景跳切 | 正文自身 |\n"
            "\n"
            "审计只做「与既有记录比对」，不做审美判断：\n"
            "「这段写得不好看」不是 finding，「这段与第 3 章档案冲突」才是。\n"
            "审美与节奏感受交用户判断，本 skill 不越位。\n"
        ),
    },
    {
        "name": "revision-methodology",
        "description": "修订打磨方法论",
        "content": (
            "---\n"
            "name: revision-methodology\n"
            "description: 修订打磨方法论\n"
            "---\n"
            "\n"
            "# 修订方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于在保留原意的前提下修订打磨章节草稿，依据审校 findings 或用户\n"
            "意见修改文本，控制改动幅度，修订后统计字数并保存草稿供用户确认。适用于\n"
            "草稿已有明确问题、需要修改落地的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **读清单定范围**：先获取前文摘要，再对照审校 findings 或用户要求，\n"
            "   列出本次要处理的问题项与优先级，明确哪些段落本轮不动。\n"
            "2. **先查设定再改字**：涉及角色或世界观的修订，先读对应档案确认正确表述，\n"
            "   再落笔——禁止凭正文反推设定，那会把漂移固化进档案之外。\n"
            "3. **逐条处理**：修正设定矛盾、补齐遗漏伏笔、理顺逻辑与衔接，保留作者原意。\n"
            "4. **控幅单点改**：只改问题点对应的句子与段落，不重排场景结构，\n"
            "   不顺手润色无关段落（文笔层面留给润色方法论）。\n"
            "5. **改后复查**：统计新字数，并回查改动是否引入新的设定矛盾或时序断裂，\n"
            "   必要时再走一次审计。\n"
            "6. **存草稿 + 变更清单**：保存草稿并向用户说明每处改动对应的 finding。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不超出指定范围：没有对应 finding 或用户要求的段落不主动大改，尤其不动情节走向。\n"
            "- 不替审校下结论：findings 的判定由审计方法论负责，修订只按结论执行。\n"
            "- 不越权改设定：发现设定本身有问题时报告给用户，\n"
            "  不得通过改正文来「绕过」设定错误。\n"
            "- 不一次改多项无关内容：改动范围越大越难回归验证，宁可分轮。\n"
            "\n"
            "## 示例\n"
            "\n"
            "按审校 findings 修订「第 12 章」：4 条 finding 全部纳入；先读角色档案确认\n"
            "正确称呼与能力上限，修正称呼、把越权能力改为档案内的替代手段；补写缺失的\n"
            "信物伏笔细节；时间线按上游第 10 章口径统一为「三日后」。其余段落保持原样；\n"
            "完成后统计字数、复查无新矛盾，保存草稿并回复改动清单。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "保存草稿前逐条确认：\n"
            "\n"
            "- [ ] 逐条闭环：每条 finding 都有对应的修改，未处理的说明原因\n"
            "- [ ] 改动克制：只改问题点所在句子或段落，无关段落零改动\n"
            "- [ ] 设定有据：所有设定相关改动都查过档案，未凭正文反推\n"
            "- [ ] 情节未动：事件结果、角色决策、场景顺序与原文一致\n"
            "- [ ] 无新矛盾：改动后复查未引入新的设定冲突或时序断裂\n"
            "- [ ] 字数已统计：向用户报告修订前后字数变化\n"
            "- [ ] 变更清单可核对：每处改动列出「改前 → 改后 → 对应 finding」\n"
            "\n"
            "## 常见误改\n"
            "\n"
            "| 误改 | 后果 | 正确做法 |\n"
            "|------|------|----------|\n"
            "| 改成另一个未记载的能力 | 漂移依旧存在 | 改为档案内确有依据的手段 |\n"
            "| 顺手重写无关段落 | 无法回归验证，且掩盖真实问题 | 只改 finding 指向处 |\n"
            "| 按正文口径统一时间线 | 与上游时间轴脱节 | 以上游时间轴为准 |\n"
            "| 把设定冲突通过改正文「绕过」 | 设定错误被永久掩盖 | 报给用户，等设定裁定 |\n"
            "\n"
            "修订的风险不在于改得少，而在于改出新的不一致——\n"
            "因此本 skill 把「复查」列为必经步骤，而非可选项。\n"
            "\n"
            "## 改动幅度口径\n"
            "\n"
            "| 问题类型 | 允许的改动幅度 | 不得触碰 |\n"
            "|----------|---------------|----------|\n"
            "| 称呼 / 术语不一致 | 仅替换该词及其指代 | 句子结构与情节 |\n"
            "| 设定漂移（能力越界） | 改写该动作的实现方式 | 事件结果与胜负 |\n"
            "| 伏笔漏收 | 增补线索段落 | 后续章节已写的走向 |\n"
            "| 时序矛盾 | 统一时间表述 | 事件发生顺序 |\n"
            "| 逻辑断裂 | 补过渡句或补一句因果 | 场景划分 |\n"
            "\n"
            "改写幅度自我约束：单章改动段落数不超过 finding 数量。\n"
            "若某条 finding 需要的改动超出上表口径，说明它不是修订问题，\n"
            "而是结构或设定问题——应停下报告，而不是在正文里绕过去。\n"
        ),
    },
    {
        "name": "worldview-methodology",
        "description": "世界观一致性方法论",
        "content": (
            "---\n"
            "name: worldview-methodology\n"
            "description: 世界观一致性方法论\n"
            "---\n"
            "\n"
            "# 世界观方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于校验角色档案与伏笔是否符合项目世界观设定，发现矛盾时给出修正\n"
            "建议而非直接改写。适用于设定档案更新、新章节引入新设定或需要全局一致性\n"
            "把关的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **先读世界观基准**：读出力量体系、地理、时代、社会规则、禁忌等\n"
            "   不可违背的约束，整理成一份基准清单。基准未读到就不要下判断。\n"
            "2. **校角色档案**：逐项检查角色的出身、能力、关系、所属势力是否与基准冲突；\n"
            "   特别注意「能力来源」这类跨条目依赖（能力依赖某资源 → 该资源在世界观中的状态）。\n"
            "3. **校伏笔走向**：伏笔内容与计划兑现方式是否越过世界观边界；\n"
            "   若伏笔要求一个世界观不允许的结果，标记为设定级矛盾而非情节问题。\n"
            "4. **查设定漂移**：把新档案/新章节用到的设定点与既有条目逐条对照，\n"
            "   找出同名不同义、同义不同名、规则前后放宽三类漂移。\n"
            "5. **校时间口径**：设定中的时代、纪年、事件先后是否与项目时间轴自洽。\n"
            "6. **输出建议清单**：逐条列矛盾点、世界观依据（引用条目原文）、建议方案。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 只建议不改写：本 skill 产出建议清单，实际修改由用户或修订方法论执行。\n"
            "- 不扩大解释设定：世界观未明示的细节不作硬性推断，标注为待确认项。\n"
            "- 与审计的职责边界：本 skill 聚焦世界观规则本身，章节内部叙事一致性问题交给审计。\n"
            "- 不硬堵创作空间：设定冲突有两种解法（改设定 / 改角色），\n"
            "  本 skill 只负责指出冲突并给出两条路，选哪条由用户拍板。\n"
            "\n"
            "## 示例\n"
            "\n"
            "校验新角色「矿脉巫师」：读世界观基准得知力量依赖地脉水晶、且设定中水晶\n"
            "早已枯竭。校档案发现该角色能力直接依赖水晶，且前文未埋再生伏笔 → 判定\n"
            "设定级矛盾。输出两条建议：① 调整能力来源为残留晶屑，② 补充枯竭例外条款\n"
            "并在前文补埋伏笔；标注建议 ① 改动面更小，交用户决定。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "建议清单交付前逐条确认：\n"
            "\n"
            "- [ ] 基准已读：所有判断都基于读到的世界观条目，未凭印象推断\n"
            "- [ ] 依据可查：每条建议引用了世界观条目原文，而非概括性说法\n"
            "- [ ] 三类漂移已查：同名不同义、同义不同名、规则前后放宽\n"
            "- [ ] 跨条目依赖已查：角色的能力来源、资源状态、势力归属均已核对\n"
            "- [ ] 伏笔越界已查：伏笔的兑现方式未要求世界观不允许的结果\n"
            "- [ ] 时间口径已查：设定中的时代、纪年与项目时间轴自洽\n"
            "- [ ] 给了两条路：每条冲突都提供「改设定」与「改角色/情节」两种解法\n"
            "\n"
            "## 三类设定漂移的识别口径\n"
            "\n"
            "| 类型 | 表现 | 判定要点 |\n"
            "|------|------|----------|\n"
            "| 同名不同义 | 同一术语在两处含义不同 | 比对术语的定义句，而非只看名称 |\n"
            "| 同义不同名 | 同一事物被换了说法 | 比对功能描述，而非只看名称 |\n"
            "| 规则放宽 | 后文允许了前文禁止的事 | 找「例外条款」是否被追溯补充 |\n"
            "\n"
            "前两类是命名问题（改动小），第三类是规则问题（改动大且影响面广）——\n"
            "本 skill 应在建议中明确标注属于哪一类，便于用户判断改动成本。\n"
            "\n"
            "## 与审计的分工\n"
            "\n"
            "两个 skill 都查一致性，但对象与结论不同：\n"
            "\n"
            "| 对比项 | audit-methodology | worldview-methodology（本 skill） |\n"
            "|--------|-------------------|-----------------------------------|\n"
            "| 对象 | 章节正文 vs 既有记录 | 设定档案 vs 世界观基准 |\n"
            "| 触发 | 草稿完成后 | 档案更新 / 新设定引入 / 全局把关 |\n"
            "| 产物 | findings 清单（含分级） | 冲突清单 + 双解法建议 |\n"
            "| 决策权 | 无（只报告） | 无（给两条路，用户拍板） |\n"
            "\n"
            "边界判定：矛盾出在「章内叙述」→ 交审计；\n"
            "矛盾出在「设定条目本身之间」→ 本 skill 负责。\n"
            "两者都涉及同一条目时，应分别成条，不复用同一条 finding。\n"
        ),
    },
    {
        "name": "polishing-methodology",
        "description": "文笔润色方法论",
        "content": (
            "---\n"
            "name: polishing-methodology\n"
            "description: 文笔润色方法论\n"
            "---\n"
            "\n"
            "# 润色方法论\n"
            "\n"
            "## 目标\n"
            "\n"
            "本 skill 用于在内容不变的前提下润色章节文笔：精炼句式、优化节奏、统一用词，\n"
            "提升阅读体验。适用于正文内容已定稿、需要文笔层面收尾打磨的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. **取前文基线**：获取前文摘要，确认既有文风、称谓、称谓变体、常用句式，\n"
            "   润色后必须与之连续，不得自成一套腔调。\n"
            "2. **逐段精炼句式**：合并冗余修饰、拆分过长句、消除重复用词，\n"
            "   保持信息量不变（同一句只改说法，不删事实）。\n"
            "3. **调节奏**：按场景性质控制句子长短与段落密度——\n"
            "   紧张段落用短句、舒缓段落用长句，避免全章同一节奏。\n"
            "4. **统一用词与指代**：同一对象全章同一称呼，同一动作全章同一动词，\n"
            "   清除同义混用（尤其角色指代与专有名词）。\n"
            "5. **查细节瑕疵**：删重复修饰、修语病与标点、确认语气与人设和场景氛围相符。\n"
            "   顺手核一遍时间表述是否相对化（避免绝对年份混入）。\n"
            "6. **收尾统计**：统计字数、向用户说明改动幅度。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不改变情节与人物行动：影响剧情走向、事件结果或角色决策的改动属于修订而非润色。\n"
            "- 不改设定表述：角色能力、称谓、世界观术语的字面是设定锚点，\n"
            "  发现它们有问题要报告，不擅自「润」成别的说法。\n"
            "- 不做结构级调整：场景顺序、段落重组与增删内容不在本 skill 范围内。\n"
            "- 保持作者风格：只清除明显冗余与瑕疵，不把文本改写成统一模板腔。\n"
            "\n"
            "## 示例\n"
            "\n"
            "润色「第 12 章」：取前文摘要确认作者惯用短句与第三人称限知；\n"
            "逐段合并冗余修饰、统一主角指代、把对峙段拆为短句提升节奏；\n"
            "核对时间表述统一为「三日后」这类相对口径；完成后统计字数并回复改动摘要，\n"
            "正文内容、情节与设定表述保持不变。\n"
            "\n"
            "## 交付前自检\n"
            "\n"
            "润色稿交付前逐条确认：\n"
            "\n"
            "- [ ] 信息未减：没有任何事实、动作、对白被删（只改说法）\n"
            "- [ ] 情节未动：事件结果、角色决策、场景顺序与原文一致\n"
            "- [ ] 设定表述未改：称谓、能力名、世界观术语保持原样\n"
            "- [ ] 文风连续：与前文的句式习惯、称谓变体一致，未自成腔调\n"
            "- [ ] 节奏有变化：紧张段短句、舒缓段长句，全章非同一节奏\n"
            "- [ ] 用词已统一：同一对象同一称呼，同一动作同一动词\n"
            "- [ ] 字数已统计：向用户报告改动幅度\n"
            "\n"
            "## 与修订的边界判定\n"
            "\n"
            "遇到不确定的改动，用一张判据表决定归谁：\n"
            "\n"
            "| 改动内容 | 归属 | 理由 |\n"
            "|----------|------|------|\n"
            "| 同一句话说法的变化 | 润色（本 skill） | 信息不变 |\n"
            "| 事件结果或角色决策变化 | 修订 | 影响剧情走向 |\n"
            "| 增删段落内容 | 修订 | 属结构级调整 |\n"
            "| 称谓 / 能力名 / 术语字面 | 都不是 → 报告用户 | 设定锚点，需设定流程 |\n"
            "\n"
            "润色最容易越界的方式是「顺手改掉读起来别扭的设定表述」——\n"
            "那些字面往往正是设定与一致性检查的锚点，改了就切断了引用链。\n"
            "因此本 skill 对设定表述一律只报告、不修改。\n"
            "\n"
            "## 常见文笔病症与处方\n"
            "\n"
            "| 病症 | 表现 | 处方 |\n"
            "|------|------|------|\n"
            "| 修饰堆叠 | 一句多个形容词叠加 | 保留最具体的一个，删其余 |\n"
            "| 长句缠绕 | 一句含多个转折与从句 | 按语义切分为两到三句 |\n"
            "| 同义混用 | 同一对象多种称呼交替 | 全章统一，必要时保留有意的变体 |\n"
            "| 节奏平板 | 全章句长接近、段落等长 | 紧张段压短、舒缓段放长 |\n"
            "| 空洞抒情 | 用形容词代替具体感受 | 换成可感的动作、细节或物件 |\n"
            "| 解释过度 | 叙述把意图与成因说尽 | 删解释，留动作与反应 |\n"
            "| 口语残留 | 出现现代口语与网络用语 | 按世界观时代口径替换 |\n"
            "\n"
            "「解释过度」与「口语残留」是最伤长篇沉浸感的两类，\n"
            "润色时应优先巡视章末与情绪高点段落——这两处最易出现。\n"
            "\n"
            "## 润色时的设定红线\n"
            "\n"
            "润色只处理文字层，不承担一致性职责，但改写过程本身会踩到一致性问题。\n"
            "遇到下列情况一律停下报告，不做「顺手修好」：\n"
            "\n"
            "- 角色称呼在章内不统一 → 属设定漂移，报告交审校 / 世界观顾问，\n"
            "  润色不得自行选定一个「更好听」的称呼\n"
            "- 时间表述前后矛盾（「次日」与「三日后」并存）→ 属时间线问题，\n"
            "  只统一为原文中证据更充分的一方并标注，不发明第三个时间口径\n"
            "- 某条伏笔的线索文字被改得读不出来 → 伏笔锚点被削弱，\n"
            "  保持线索物名称与可识别特征原样\n"
            "\n"
            "一句话原则：润色可以让文字更好读，但不能让任何设定锚点变得不可追溯。\n"
            "宁可留下读起来稍别扭的表述，也不要切断引用链。\n"
        ),
    },
]
"""内置 6 Skill 出厂配置（spec §5.3，目录名 ∈ BUILTIN_SKILL_NAMES → source="builtin" 只读）."""


def _source_of(name: str) -> str:
    """source 判定：目录名 ∈ BUILTIN_SKILL_NAMES → "builtin"，否则 "user_upload"."""
    return "builtin" if name in BUILTIN_SKILL_NAMES else "user_upload"


def _mtime_iso(path: Path) -> str:
    """文件 mtime → ISO 8601 字符串（UTC，datetime.fromisoformat 可解析）."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _frontmatter_name(content: str) -> str:
    """提取 content frontmatter 的 name 原值（未校验；缺失 → ""）."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        if key.strip() == "name":
            return value.strip().strip('"').strip("'")
    return ""


def _parse_upload(content: str, directory_name: str) -> SkillMetadata:
    """解析并校验 content frontmatter；失败 → SkillFrontmatterError（422）."""
    try:
        return parse_skill_metadata(content, directory_name)
    except SkillValidationError as err:
        raise SkillFrontmatterError() from err


class SkillService:
    """Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

    Args:
        skills_root: skill 文件系统真源根（data_dir/skills）.
        agent_repository: Agent 仓储端口（删除级联清引用用）.
    """

    def __init__(
        self,
        *,
        skills_root: Path,
        agent_repository: AgentRepositoryProtocol,
    ) -> None:
        self._skills_root = skills_root
        self._agent_repo = agent_repository

    async def create(self, data: SkillCreate) -> Skill:
        """创建用户上传 Skill（frontmatter 解析 → 同名查重 → 写文件）.

        目录名 = frontmatter name（parse_skill_metadata 强制 name == 目录名
        且匹配 N2）；同名目录已存在 → SkillNameConflictError（422）；成功
        → 写出 skills_root/<name>/SKILL.md（content 原样）并返回实体。
        """
        meta = _parse_upload(data.content, _frontmatter_name(data.content))
        name = meta.name
        target_dir = self._skills_root / name
        if target_dir.exists():
            raise SkillNameConflictError()
        self._skills_root.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(data.content, encoding="utf-8")
        logger.info("创建 Skill: name=%s", name)
        created: Skill = Skill(
            name=name,
            description=meta.description,
            content=data.content,
            source="user_upload",
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )
        await publish_change("skill", "create", name, None)
        return created

    async def get(self, name: str) -> Skill:
        """按目录名读 skills_root/<name>/SKILL.md → Skill；缺失 → SkillNotFoundError（404）."""
        skill_file = self._skills_root / name / "SKILL.md"
        if not skill_file.is_file():
            raise SkillNotFoundError()
        content = skill_file.read_text(encoding="utf-8")
        description = ""
        try:
            description = parse_skill_metadata(content, name).description
        except SkillValidationError:
            description = ""
        return Skill(
            name=name,
            description=description,
            content=content,
            source=_source_of(name),
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill（扫描 skills_root/*/SKILL.md 解析元数据，按 name 升序）."""
        if not self._skills_root.is_dir():
            return []
        items: builtins.list[Skill] = []
        for child in sorted(self._skills_root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            content = skill_file.read_text(encoding="utf-8")
            description = ""
            try:
                description = parse_skill_metadata(content, child.name).description
            except SkillValidationError:
                description = ""
            items.append(
                Skill(
                    name=child.name,
                    description=description,
                    content=content,
                    source=_source_of(child.name),
                    created_at=_mtime_iso(skill_file),
                    updated_at=_mtime_iso(skill_file),
                )
            )
        return sorted(items, key=lambda s: s.name)

    async def update(self, name: str, data: SkillUpdate) -> Skill:
        """部分更新 Skill（文件系统真源）.

        None 值 = 不修改（exclude_unset 浅合并，同 F1/F13）；content 变更
        → 整文件写回 + 按新 frontmatter 重解析（非法 → SkillFrontmatterError）；
        内置目录 → SkillBuiltinError（409）；目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "content" in updates:
            content = updates["content"]
            _parse_upload(content, name)
            skill_file = self._skills_root / name / "SKILL.md"
            skill_file.write_text(content, encoding="utf-8")
            logger.info("更新 Skill: name=%s", name)
            await publish_change("skill", "update", name, None)
            return await self.get(name)
        if not updates:
            return existing
        merged = existing.model_copy(update=updates)
        logger.info("更新 Skill（元数据合并）: name=%s", name)
        return merged

    async def delete(self, name: str) -> None:
        """删除 Skill（内置只读 → 409；被引用 → 先级联清引用再删目录）.

        全部引用 Agent 的 update（清 skill_ids）先于目录删除（spec §5.6）；
        目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        refs = await self._agent_repo.list_agents_by_skill(name)
        for agent in refs:
            agent.skill_ids = [sid for sid in agent.skill_ids if sid != name]
            await self._agent_repo.update(agent)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以完整实体单参调用（G2 repo 签名双参形态兼容，见 agent_repo.update）
        target_dir = self._skills_root / name
        if target_dir.is_dir():
            shutil.rmtree(target_dir)
        logger.info("删除 Skill: name=%s", name)
        await publish_change("skill", "delete", name, None)

    async def duplicate(self, name: str, *, new_name: str | None = None) -> Skill:
        """复制 Skill（#485 语义延续 + #522 文件系统真源）.

        新名 = 指定名或 f"{name}-copy"；副本目录已存在 → SkillNameConflictError
        （422）；源缺失 → SkillNotFoundError；成功 → 复制整个目录并返回
        副本实体（source="user_upload"）。
        """
        existing = await self.get(name)
        target_name = new_name or f"{name}-copy"
        target_dir = self._skills_root / target_name
        if target_dir.exists():
            raise SkillNameConflictError()
        src_dir = self._skills_root / name
        shutil.copytree(src_dir, target_dir)
        logger.info("复制 Skill: name=%s → %s", name, target_name)
        duplicated: Skill = Skill(
            name=target_name,
            description=existing.description,
            content=existing.content,
            source="user_upload",
            created_at=_mtime_iso(target_dir / "SKILL.md"),
            updated_at=_mtime_iso(target_dir / "SKILL.md"),
        )
        await publish_change("skill", "create", target_name, None)
        return duplicated


def ensure_builtin_skills(skills_root: Path) -> int:
    """幂等写出 6 个内置 SKILL.md（ADR-039 D3b=A 启动回补）.

    目录缺失/内置缺失 → 写出（content 含 frontmatter name=slug，可被
    parse_skill_metadata 校验）；已存在 → 跳过；返回本次实际写入数。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for spec in BUILTIN_SKILL_SPECS:
        target = skills_root / spec["name"] / "SKILL.md"
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec["content"], encoding="utf-8")
        written += 1
    return written


async def migrate_skills_from_db(session: AsyncSession, skills_root: Path) -> int:
    """一次性迁移旧 skills 表 user_upload 行 → 写出文件后清表（ADR-039 D3c=A）.

    raw SQL 实现（sqlalchemy.text），不得依赖 SkillORM；表不存在 → 0（不抛
    错、不重建旧表）；迁移后 DELETE 全部行（含 builtin 行）；返回迁移条数。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    try:
        result = await session.execute(
            text("SELECT name, content FROM skills WHERE source = 'user_upload'")
        )
    except Exception:
        # 旧库无 skills 表（全新安装/表已被清）→ 无存量可迁移
        await session.rollback()
        return 0
    rows = result.all()
    migrated = 0
    for row in rows:
        name = str(row[0])
        content = str(row[1])
        skill_dir = skills_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        migrated += 1
    await session.execute(text("DELETE FROM skills"))
    await session.commit()
    logger.info("迁移旧 skills 表: %s 条 user_upload 行写出文件", migrated)
    return migrated
