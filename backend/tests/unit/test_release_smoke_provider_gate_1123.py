"""#1123 发布冒烟脚本 ↔ provider 探测门禁契约测试（静态）。

背景：0.14.0-rc4 打 tag 后发布流水线在「Packaged kernel smoke (RAG module integrity)」
挂掉、无产物产出。根因 = #1085（#936 C 项）给 `PATCH /provider-configs/{id}` 加了
「保存前探测门禁」（无 API Key → 400 拒绝），同批修了 10 个 E2E 调用点却漏了
release.yml 的冒烟 PATCH —— CI runner 无 zhipu key，PATCH 必然 400。

本文件把「release.yml 冒烟里对 provider-configs 的写调用必须绕过探测门禁」
固化为静态契约（对齐 test_packaging_skills_contract.py 模式：打包/发布配置漂移 → CI 红），
使「改门禁语义漏改旧调用点」这类回归在 CI 而非打 tag 时才暴露。

对应门禁实现：backend/src/inkflow/domain/services/provider_config_service.py::_probe_error
放行通道：backend/src/inkflow/api/routers/provider_configs.py（`force` 查询参数）
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/tests/unit → 仓库根
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _smoke_step_script() -> str:
    """返回 release.yml 中「Packaged kernel smoke」步骤的脚本文本。

    只取该 step（到下一个同级 `      - name:` 为止），避免其他 step 的
    provider-configs 调用误判。
    """
    src = RELEASE_YML.read_text(encoding="utf-8")
    marker = "Packaged kernel smoke"
    assert marker in src, f"release.yml 缺少「{marker}」步骤（#1123 契约前提）"
    tail = src[src.index(marker) :]
    nxt = re.search(r"\n      - name:", tail)
    return tail[: nxt.start()] if nxt else tail


def _provider_config_write_uris(script: str) -> list[str]:
    """提取脚本内对 provider-configs/{id} 的**写调用** URI（排除只读 GET）。"""
    uris: list[str] = []
    for line in script.splitlines():
        if "provider-configs" not in line:
            continue
        # 只读列表端点 /provider-configs（无路径段）不需要放行
        if "-Method PATCH" not in line and "-Method PUT" not in line:
            continue
        for match in re.finditer(r'Uri\s+"([^"]*provider-configs[^"]*)"', line):
            uris.append(match.group(1))
    return uris


def test_release_smoke_provider_config_writes_bypass_probe_gate():
    """#1123: 冒烟脚本对 provider-configs 的写调用必须带 force=true（绕过探测门禁）。

    CI runner 无 LLM key → 不加 force 必 400「缺少 API Key，无法探测」→ 阻断发布。
    """
    script = _smoke_step_script()
    write_uris = _provider_config_write_uris(script)
    assert write_uris, (
        "未在冒烟脚本中找到 provider-configs 写调用——若已移除，请同步删除本契约测试（#1123）"
    )
    for uri in write_uris:
        assert "force=true" in uri, (
            f"provider-configs 写调用缺少 force=true：{uri}\n"
            "无 key 环境（CI runner）会被 #1085 探测门禁以 400 拒绝，导致打 tag 即挂（#1123）"
        )
