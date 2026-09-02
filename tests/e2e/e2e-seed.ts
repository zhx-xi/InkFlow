/**
 * S3f-T3 种子基建（contract-s3f-t3 §1.3 R4）：buildSeed 固定中文内容 + seedProjectViaApi
 * 经内核 API 落库执行器。
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec 与 vitest 双加载。
 * 结构不变量以 tests/e2e/e2e-seed.test.ts 为断言级契约（GREEN 实现不可改测试）：
 * - characters：3 角色（名互异、name/personality 非空）
 * - worlds：2 级树 = 恰 1 根 + ≥1 子（子经 parentName 引用根名；content/category 非空）
 * - outlines：overall / volume / chapter 三级各 ≥1
 * - volumes：2 卷共 3 章，每章正文 ≥50 字中文；恰 1 章 title 含「未挂卷」标记
 *   （执行器落库时该章 volume_id=null 归「未分组」，其余挂卷章 volume_id 显式指定）
 *
 * POST body 形状对齐既有内联 helper 实测：volumes {title}、chapters {title, volume_id,
 * content}、characters {name, personality, extra: {role_rank}}（#833 API 创建必填
 * role_rank，e2e-library/pipeline-gaps helper 同款）、world-settings {name, category,
 * content, parent_id}、outlines {name, level, parent_id, chapter_id}。
 * 唯一后缀由调用方经 projectName 传入（E2E 惯例 `${Date.now()}`，#167/#366 先例）。
 */

/** 未挂卷标记：执行器把含该标记的章落为 volume_id=null（归「未分组」） */
const UNGROUPED_MARKER = '未挂卷';

export interface SeedCharacter {
  name: string;
  personality: string;
}

export interface SeedWorld {
  name: string;
  content: string;
  category: string;
  /** 父条目名（省略 = 树根） */
  parentName?: string;
}

export interface SeedOutline {
  name: string;
  level: 'overall' | 'volume' | 'chapter';
  /** level=chapter 时关联的写作章节标题（可省略 = 不关联） */
  chapterTitle?: string;
}

export interface SeedChapter {
  title: string;
  content: string;
}

export interface SeedVolume {
  title: string;
  chapters: SeedChapter[];
}

export interface SeedContent {
  projectName: string;
  characters: SeedCharacter[];
  worlds: SeedWorld[];
  outlines: SeedOutline[];
  volumes: SeedVolume[];
}

/** 固定中文种子内容（唯一后缀经 projectName 透传，正文 ≥50 字） */
export function buildSeed(projectName: string): SeedContent {
  return {
    projectName,
    characters: [
      {
        name: '云清扬',
        personality: '性情沉静，剑术通明，遇事从容，重信守诺，常于危局中觅得一线生机。',
      },
      {
        name: '苏晚棠',
        personality: '聪慧机敏，善察人心，言辞温婉却锋芒内敛，关键时刻敢于决断。',
      },
      {
        name: '顾长风',
        personality: '豪爽仗义，快意恩仇，好酒好友，遇不平事必拔刀相助，从不畏强。',
      },
    ],
    worlds: [
      {
        name: '云州大陆',
        category: '地理',
        content:
          '云州大陆西高东低，北疆绵延雪山终年不化，南境泽国水网密布，东临沧海，宗门与皇朝并存，灵脉多藏于深山大泽，修行者以登天路为毕生所求。',
      },
      {
        name: '凌霄剑宗',
        category: '宗门',
        parentName: '云州大陆',
        content:
          '坐镇云州东境凌云峰，以剑入道传承千年，门下弟子三千，剑阁藏历代剑谱，为天下剑修心向往之的修行圣地。',
      },
      {
        name: '天枢皇朝',
        category: '势力',
        parentName: '云州大陆',
        content:
          '疆域横贯云州中西部，都城天枢城雄踞平原，皇帝与宗门订立盟约共治天下，边军世代镇守北疆雪山关隘。',
      },
    ],
    outlines: [
      { name: '云州风云总纲', level: 'overall' },
      { name: '第一卷纲要', level: 'volume' },
      { name: '第一章纲要', level: 'chapter', chapterTitle: '第一章 山雨欲来' },
    ],
    volumes: [
      {
        title: '第一卷 风起云州',
        chapters: [
          {
            title: '第一章 山雨欲来',
            content:
              '凌霄剑宗外门弟子云清扬奉师命下山，途经青石镇时恰逢暴雨，客栈中偶遇苏晚棠与顾长风，三人因一桩旧案卷入天枢皇朝与凌霄剑宗之间的暗流，山雨欲来，杀机渐起。',
          },
        ],
      },
      {
        title: '第二卷 惊雷乍响',
        chapters: [
          {
            title: `第二章 ${UNGROUPED_MARKER}的孤章`,
            content:
              '皇城夜宴上，一道来自北疆的密旨悄然传至，剑宗密使殒命驿道，苏晚棠循着蛛丝马迹追至荒郊古庙，却发现所有线索都指向一位本不该出现的故人，真相在长夜中愈发扑朔迷离。',
          },
          {
            title: '第三章 峰回路转',
            content:
              '顾长风率旧部驰援天枢城，与云清扬在城头重逢，二人合谋诈降破局，将皇朝与宗门的盟约撕开一道裂隙；晨光破晓时，苏晚棠送来密信，指明幕后主使竟是剑宗内门长老，前路再度峰回路转。',
          },
        ],
      },
    ],
  };
}

/**
 * 经内核 API 落库执行器：建项目 → 角色/世界观/卷章/大纲三级树。
 * fetchKernel 签名：<T>(method, path, body?) → 已解析 JSON（204/空响应返回 undefined）。
 * 返回 ORM 整数主键（与后端 uuid.UUID(int=id) 对齐，供后续断言路径复用）。
 */
export async function seedProjectViaApi(
  fetchKernel: <T>(method: string, path: string, body?: unknown) => Promise<T>,
  seed: SeedContent
): Promise<{ projectId: number; chapterIds: number[] }> {
  const project = await fetchKernel<{ id: string | number }>('POST', '/api/v1/projects', {
    name: seed.projectName,
  });
  const projectId = toIdInt(project.id);
  const base = `/api/v1/projects/${projectId}`;

  // ① 角色（#833：创建必填 extra.role_rank——API 直灌同样生效，镜像 e2e-library helper）
  for (const character of seed.characters) {
    await fetchKernel('POST', `${base}/characters`, {
      name: character.name,
      personality: character.personality,
      extra: { role_rank: 'major' },
    });
  }

  // ② 世界观 2 级树：先建根（无 parentName），再建子（parent_id 引用根）
  const worldIds = new Map<string, string>();
  for (const world of seed.worlds) {
    if (world.parentName) {
      continue;
    }
    const created = await fetchKernel<{ id: string }>('POST', `${base}/world-settings`, {
      name: world.name,
      category: world.category,
      content: world.content,
    });
    worldIds.set(world.name, created.id);
  }
  for (const world of seed.worlds) {
    const parentId = world.parentName ? worldIds.get(world.parentName) : undefined;
    if (!world.parentName) {
      continue;
    }
    if (!parentId) {
      throw new Error(`seed 世界观父条目不存在: ${world.parentName}`);
    }
    const created = await fetchKernel<{ id: string }>('POST', `${base}/world-settings`, {
      name: world.name,
      category: world.category,
      content: world.content,
      parent_id: parentId,
    });
    worldIds.set(world.name, created.id);
  }

  // ③ 卷 + 章（含未挂卷章：volume_id 缺省 = 「未分组」；挂卷章 order_index 显式）
  const chaptersByTitle = new Map<string, string>();
  const chapterIds: number[] = [];
  for (const volume of seed.volumes) {
    const createdVolume = await fetchKernel<{ id: string }>('POST', `${base}/volumes`, {
      title: volume.title,
    });
    let orderIndex = 0;
    for (const chapter of volume.chapters) {
      const ungrouped = chapter.title.includes(UNGROUPED_MARKER);
      const createdChapter = await fetchKernel<{ id: string }>('POST', `${base}/chapters`, {
        title: chapter.title,
        content: chapter.content,
        ...(ungrouped
          ? {}
          : { volume_id: createdVolume.id, order_index: orderIndex++ }),
      });
      chaptersByTitle.set(chapter.title, createdChapter.id);
      chapterIds.push(toIdInt(createdChapter.id));
    }
  }

  // ④ 大纲三级树：overall → volume（parent_id）→ chapter（parent_id + chapter_id 关联）
  const createdOutlineIds: string[] = [];
  for (const outline of seed.outlines) {
    if (outline.level === 'overall') {
      const created = await fetchKernel<{ id: string }>('POST', `${base}/outlines`, {
        name: outline.name,
        level: 'overall',
      });
      createdOutlineIds.push(created.id);
    }
  }
  const overallId = createdOutlineIds[0];
  if (!overallId) {
    throw new Error('seed 大纲缺少 overall 根节点');
  }
  let volumeOutlineId: string | undefined;
  for (const outline of seed.outlines) {
    if (outline.level === 'volume') {
      const created = await fetchKernel<{ id: string }>('POST', `${base}/outlines`, {
        name: outline.name,
        level: 'volume',
        parent_id: overallId,
      });
      volumeOutlineId = created.id;
      createdOutlineIds.push(created.id);
    }
  }
  if (!volumeOutlineId) {
    throw new Error('seed 大纲缺少 volume 层级节点');
  }
  for (const outline of seed.outlines) {
    if (outline.level !== 'chapter') {
      continue;
    }
    const chapterId = outline.chapterTitle
      ? chaptersByTitle.get(outline.chapterTitle)
      : undefined;
    await fetchKernel('POST', `${base}/outlines`, {
      name: outline.name,
      level: 'chapter',
      parent_id: volumeOutlineId,
      ...(chapterId ? { chapter_id: chapterId } : {}),
    });
  }

  return { projectId, chapterIds };
}

/** 后端主键 = ORM int（API 序列化为 uuid.UUID(int=id) 字符串）→ 还原为整数 id */
function toIdInt(id: string | number): number {
  if (typeof id === 'number') {
    return id;
  }
  const compact = id.replace(/-/g, '');
  if (/^\d+$/.test(compact)) {
    return Number(compact);
  }
  return Number(BigInt(`0x${compact}`));
}
