# 原型自托管 serif 字体（#1460）

`design/GUI/*/*.html` 的 `--font-serif` 原先指向**本机字体栈**
（`"Noto Serif SC","Source Han Serif SC","SimSun","宋体",Georgia,serif`）。
字体栈是「机器相关」的：CI runner 上解析到的字体与出图机器不同 → 字形栅格化不同
→ 层② 原型 PNG↔HTML 同源性门禁（`ci_cd/check_gui_png_homology.py`）大面积**假漂移**
（PR #1459 的 CI run 实测 **91/107 漂移**，bbox 一律自 `(44, 16)` 起、maxdiff 129–215）。

本目录把 serif 字体**随仓库分发**，让原型渲染与字体环境无关：门禁可以进 CI，
原型截图在任何机器/任何协作者上都是同一张图。

## 文件

| 文件 | 说明 |
|------|------|
| `inkflow-serif-400.woff2` | 字重 400 子集（`--font-serif` 默认字重；如写作页 `.tree-seal .seal`） |
| `inkflow-serif-600.woff2` | 字重 600 子集（原型里 serif 的主流字重：品牌字 / 页标题 / 卡片标题 / 对话框标题） |
| `OFL.txt` | 字体许可原文 |
| `build-subset.py` | 子集构建脚本（可复现；需网络） |

## 许可与来源

- **字体**：Noto Serif SC（Static，v2.003-H1）
- **版权**：`(c) 2017-2024 Adobe (http://www.adobe.com/)`，`(c) 2012 Google Inc.`
- **许可**：SIL Open Font License 1.1（**OFL-1.1**，允许再分发/子集化；见 `OFL.txt`）
- **分发渠道**：Google Fonts（`fonts.googleapis.com` → 字体文件 `fonts.gstatic.com`）
- **取法**（脚本里实现）：Google Fonts CSS API 在普通 UA 下只返回按 `unicode-range`
  切片的 woff2（覆盖不到原型用到的箭头/圈号等符号）；改用 legacy UA 请求同一 API 会经
  `/l/font?kit=` 返回**完整字体**（EOT 容器，body 即完整 SFNT）→ 剥离容器头 → 子集化。

## 子集化方式

```powershell
uv run --no-project --with fonttools --with brotli python `
    design/GUI/_assets/fonts/build-subset.py
```

- **字符集**：`design/GUI/**/*.html` 里出现过的全部字符（含 JS 字符串与文案），
  当前 **1152 个**（其中 CJK 1011）。
- **选项**：`--layout-features=* --name-IDs=* --name-legacy --notdef-glyph --notdef-outline`
  （保留 kern 等排版特性，贴近完整字体的排版结果）。
- **族名改写**：子集内改名为 `InkFlow Serif`——与系统里可能安装的 `Noto Serif SC` 区分开，
  使「@font-face 加载失败」立刻表现为回退到别的字体，而不是「看起来一样」把故障藏起来。
- **体积**：`inkflow-serif-400.woff2` + `inkflow-serif-600.woff2` 合计 **≈ 378 KB**
  （未子集的完整字体为 14.8 MB / 单字重）。

## 维护

新增/修改原型文案若引入了**字体里没有的新字符**，`ci_cd/tests/test_gui_selfhost_font.py`
的覆盖率用例会失败。此时：

1. 重跑上面的 `build-subset.py`（字符集自动从原型 HTML 重新收集）；
2. 重出受影响的页面 PNG（`design/GUI/_tools/shot-*.cjs`）。

## 残留的机器相关性（已知边界）

完整 Noto Serif SC 本身**不含**以下字符，它们仍由系统字体兜底（不在本子集内）：

- `▸` `▾`（详情/折叠三角，见 writing 页上下文面板与思考块）→ 落到 Windows 符号字体；
- `✅` `📎` `🔴` `🗺` `🧠` 等 emoji → 落到系统 emoji 字体；
- `\n`、U+FE0F（变体选择符）：非「可见字形」意义上的字符。

层② 门禁在 CI 与本机均为 Windows 环境，上述兜底字体一致；**若换到非 Windows 渲染端，
这几处仍可能产生漂移**——届时按门禁的豁免表登记，不要静默放宽阈值。
