/**
 * F40 #259 Skill frontmatter 解析（spec §2.2 契约 + §5.4 上传预览）：
 * 镜像后端 skill_service._parse_frontmatter 规则，前端预览阶段直接提示错误，不调后端。
 */

/** name 契约：1-64 位小写字母 / 数字 / 连字符（与后端 _NAME_PATTERN 一致） */
const NAME_PATTERN = /^[a-z0-9-]{1,64}$/;

/** 解析结果：name/description 必填；tags 可选（无 tags 行 → []） */
export interface SkillFrontmatter {
  name: string;
  description: string;
  tags: string[];
}

/** frontmatter 解析错误（message 为可展示中文） */
export class SkillFrontmatterError extends Error {
  constructor(message = 'frontmatter 不合法') {
    super(message);
    this.name = 'SkillFrontmatterError';
  }
}

/**
 * 解析 SKILL.md frontmatter：
 * - 首行 trim 后必须为 ---（缺 → 抛 SkillFrontmatterError）；
 * - 逐行 key: value（跳过空行 / # 注释行），遇闭合 --- 结束；未闭合 → 抛错；
 * - name 必填且匹配 ^[a-z0-9-]{1,64}$；description 必填；缺失/非法 → 抛错；
 * - tags 可选，`tags: a, b` 逗号分隔解析为数组。
 */
export function parseSkillFrontmatter(content: string): SkillFrontmatter {
  const lines = content.split(/\r?\n/);
  if (lines.length === 0 || lines[0].trim() !== '---') {
    throw new SkillFrontmatterError('frontmatter 必须以 --- 开头');
  }

  const fields: Record<string, string> = {};
  let closed = false;
  for (const line of lines.slice(1)) {
    const stripped = line.trim();
    if (stripped === '---') {
      closed = true;
      break;
    }
    if (!stripped || stripped.startsWith('#')) continue;
    const sep = stripped.indexOf(':');
    if (sep === -1) continue;
    const key = stripped.slice(0, sep).trim();
    // 镜像后端 strip 语义：先剥双引号，再剥单引号
    const value = stripped
      .slice(sep + 1)
      .trim()
      .replace(/^"+/, '')
      .replace(/"+$/, '')
      .replace(/^'+/, '')
      .replace(/'+$/, '');
    fields[key] = value;
  }

  if (!closed) throw new SkillFrontmatterError('frontmatter 未闭合（缺少结束 ---）');

  const name = fields['name'] ?? '';
  const description = fields['description'] ?? '';
  if (!name) throw new SkillFrontmatterError('缺少 name 字段');
  if (NAME_PATTERN.test(name) === false) {
    throw new SkillFrontmatterError('name 必须为 1-64 位小写字母 / 数字 / 连字符');
  }
  if (!description) throw new SkillFrontmatterError('缺少 description 字段');

  const tags = (fields['tags'] ?? '')
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '');
  return { name, description, tags };
}
