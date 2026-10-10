"""#1484 RED 契约 —— CLI `inkflow audit batch`（批量章节审计入口 + 断点续跑 + 聚合）.

契约（GREEN 实现必须满足，spec f34 §4 / §5.8 v1.6）:
- `audit batch -p <项目>`：枚举章节 → 逐章 `POST .../audit`（202）→ 轮询
  `GET /audit-logs/{log_id}/status` 至终态 → `GET /audit-logs/{log_id}` 取 findings
  → 聚合出报告（Markdown 清单 + JSON），退出 0。
- `--chapters 1-2`：1-based 序号区间过滤；范围外章节**不派发**（负例守护）。
- `--resume`：断点依据 = `audit_logs` 中该章存在**审计记录**（`run_status='completed'`
  **且** `severity_summary` 为审计计数格式；**F44 草稿生命周期 / agentic 动作行不计入**——
  #1562）→ 已完成章节**不重复派发**；`failed` 不算已完成。
- 默认串行（同时最多一章在 running）；`--concurrency 2` 限并发 2。
- 单章 `run_status='failed'` → **不中断整批**（记入失败清单，批次退出 0）。
- 报告按**检查项 / 严重度**双视图归类，计数与各章 findings 之和一致（防丢）。
- `--out PATH` → Markdown 写 PATH、JSON 写同主名 `.json`；省略 = 只打印 stdout（不落盘）。
- 用法错误（区间非法 / `--concurrency < 1`）→ 退出 2；过滤后无匹配章节 → 退出 1。

F38 恒 HTTP 模式（#169）: mock 目标 = `inkflow.cli.commands.audit` 命名空间的
`ensure_kernel` + `InkFlowHTTPClient`（与 tests/cli/test_cli_audit.py 同轨）。

依据: issue #1484 + specs/f34-chapter-audit/spec.md §4 / §5.8（v1.6）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands import audit as audit_mod
from inkflow.cli.commands.audit import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = "2026-10-07T10:00:00Z"


def _cid(i: int) -> str:
    """第 i 章（1-based）的 UUID（deterministic）."""
    return str(uuid.UUID(int=i))


def _chapters(n: int) -> list[dict]:
    """构造 GET /projects/{pid}/chapters 的 items（order_index 升序 = 序号顺序）."""
    return [
        {
            "id": _cid(i),
            "project_id": str(PID),
            "title": f"第 {i} 章",
            "order_index": float(i),
            "word_count": 1000,
        }
        for i in range(1, n + 1)
    ]


def _finding(check_type: str, severity: str, message: str) -> dict:
    return {
        "check_type": check_type,
        "severity": severity,
        "message": message,
        "suggestion": "",
        "ref_entity_id": None,
        "ref_entity_name": "",
        "context": "",
    }


class _FakeClient:
    """内核 HTTP 面替身：章节枚举 / 派发 / 轮询 / 明细 / 审计记录列表."""

    def __init__(
        self,
        chapters: list[dict],
        *,
        findings: dict[str, list[dict]] | None = None,
        fail: tuple[str, ...] = (),
        logs: list[dict] | None = None,
        poll_running: int = 1,
        reuse_completed: tuple[str, ...] = (),
    ) -> None:
        self.chapters = list(chapters)
        self.findings = dict(findings or {})
        self.fail = set(fail)
        self.logs = list(logs or [])
        self.poll_running = poll_running
        self.reuse_completed = set(reuse_completed)
        self.posted: list[str] = []
        self.get_paths: list[str] = []
        self.inflight = 0
        self.max_inflight = 0
        self._remaining: dict[str, int] = {}
        self._settled: set[str] = set()

    # -- context manager（命令侧 `async with client`）--
    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    # -- helpers --
    @staticmethod
    def _log_id(cid: str) -> str:
        return f"log-{cid[-12:]}"

    def _cid_of(self, log_id: str) -> str:
        suffix = log_id[len("log-") :]
        for ch in self.chapters:
            if ch["id"][-12:] == suffix:
                return str(ch["id"])
        raise AssertionError(f"未知 log_id: {log_id}")

    def _title(self, cid: str) -> str:
        return next(ch["title"] for ch in self.chapters if ch["id"] == cid)

    def _settle(self, cid: str) -> None:
        if cid not in self._settled:
            self._settled.add(cid)
            self.inflight -= 1

    def _status(self, log_id: str, cid: str, run_status: str, error: str) -> dict:
        return {
            "log_id": log_id,
            "run_status": run_status,
            "status": "pending",
            "degraded": False,
            "error": error,
            "chapter_id": cid,
            "chapter_title": self._title(cid),
            "created_at": TS,
        }

    def _detail(self, log_id: str, cid: str) -> dict:
        return {
            "id": log_id,
            "project_id": str(PID),
            "chapter_id": cid,
            "chapter_title": self._title(cid),
            "status": "pending",
            "run_status": "completed",
            "severity_summary": "",
            "summary": "",
            "degraded": False,
            "note": "",
            "created_at": TS,
            "confirmed_at": None,
            "error": "",
            "findings": list(self.findings.get(cid, [])),
        }

    # -- HTTP surface --
    async def post(self, path: str, *, params: object = None, json: object = None, **kw: object):
        assert path.endswith("/audit"), f"意外 POST 路径: {path}"
        cid = path.split("/")[4]
        self.posted.append(cid)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        if cid in self.reuse_completed:
            self._settle(cid)
            return {"log_id": self._log_id(cid), "status": "completed"}
        self._remaining[cid] = self.poll_running
        return {"log_id": self._log_id(cid), "status": "running"}

    async def get(self, path: str, *, params: dict | None = None, **kw: object):
        self.get_paths.append(path)
        if path == f"/projects/{PID}/chapters":
            offset = int((params or {}).get("offset", 0))
            limit = int((params or {}).get("limit", 50))
            return {
                "items": self.chapters[offset : offset + limit],
                "total": len(self.chapters),
                "offset": offset,
                "limit": limit,
            }
        if path == f"/projects/{PID}/audit-logs":
            offset = int((params or {}).get("offset", 0))
            limit = int((params or {}).get("limit", 20))
            return {"total": len(self.logs), "logs": self.logs[offset : offset + limit]}
        if path.endswith("/status"):
            log_id = path.split("/")[-2]
            cid = self._cid_of(log_id)
            if self._remaining.get(cid, 0) > 0:
                self._remaining[cid] -= 1
                return self._status(log_id, cid, "running", "")
            self._settle(cid)
            if cid in self.fail:
                return self._status(log_id, cid, "failed", "审计任务失败: boom")
            return self._status(log_id, cid, "completed", "")
        if path.startswith("/audit-logs/"):
            log_id = path.split("/")[-1]
            return self._detail(log_id, self._cid_of(log_id))
        raise AssertionError(f"意外路径: {path}")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（NO_COLOR 规避 FORCE_COLOR 渲染坑，项目惯例）."""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """批量轮询间隔归零（测试不真等；raising=False 使本契约为 RED 时的纯 FAIL）."""
    monkeypatch.setattr(audit_mod, "_BATCH_POLL_INTERVAL", 0, raising=False)


def _invoke_install(client: _FakeClient, args: list[str], *, json_output: bool = False):
    """安装 mock（ensure_kernel + InkFlowHTTPClient）并跑一次 batch 命令."""
    handle = SimpleNamespace(
        port=38291, token="t", pid=1, version="0.1.0", started_at="", reused=True
    )
    runner = CliRunner(env={"NO_COLOR": "1"})
    with (
        patch("inkflow.cli.commands.audit.ensure_kernel", AsyncMock(return_value=handle)),
        patch("inkflow.cli.commands.audit.InkFlowHTTPClient", return_value=client),
    ):
        return runner.invoke(app, args, obj=CliContext(json_output=json_output))


# ---------------------------------------------------------------------------
# 逐章派发 + 聚合报告
# ---------------------------------------------------------------------------


class TestBatchDispatchAndAggregate:
    """`audit batch -p <项目>` — 逐章派发并聚合出报告（Markdown + JSON）."""

    def _three_chapters(self) -> _FakeClient:
        return _FakeClient(
            _chapters(3),
            findings={
                _cid(1): [
                    _finding("character_drift", "error", "人设冲突"),
                    _finding("word_count", "info", "字数偏少"),
                ],
                _cid(2): [
                    _finding("setting_drift", "warning", "设定疑似矛盾"),
                    _finding("cross_chapter", "warning", "跨章断点"),
                ],
            },
        )

    def test_dispatches_every_chapter_and_prints_markdown(self, cli_runner) -> None:
        """默认人类输出：Markdown 报告（双视图 + 章节清单）落 stdout，退出 0."""
        fake = self._three_chapters()
        result = _invoke_install(fake, ["batch", "-p", str(PID)])

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2), _cid(3)]
        assert "## 按严重度归类" in result.stdout
        assert "## 按检查项归类" in result.stdout
        assert "## 章节清单" in result.stdout
        for i in (1, 2, 3):
            assert f"第 {i} 章" in result.stdout

    def test_json_report_counts_equal_findings_sum(self, cli_runner) -> None:
        """--json：双视图计数 == 各章 findings 之和（计数断言防丢）."""
        fake = self._three_chapters()
        result = _invoke_install(fake, ["batch", "-p", str(PID)], json_output=True)

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)["data"]
        assert data["findings_total"] == 4
        assert data["by_severity"] == {"error": 1, "warning": 2, "info": 1}
        assert sum(data["by_severity"].values()) == data["findings_total"]
        assert sum(data["by_check_type"].values()) == data["findings_total"]
        assert data["by_check_type"]["character_drift"] == 1
        per_chapter = [len(ch["findings"]) for ch in data["chapters"]]
        assert sum(per_chapter) == data["findings_total"]
        assert data["audited"] == 3
        assert data["failed"] == 0

    def test_progress_goes_to_stderr_so_stdout_stays_parseable(self, cli_runner) -> None:
        """--json 模式下进度行走 stderr（stdout 仅信封，可直接 json.loads）."""
        fake = self._three_chapters()
        result = _invoke_install(fake, ["batch", "-p", str(PID)], json_output=True)

        assert result.exit_code == 0
        json.loads(result.stdout)
        assert "[1/3]" in result.stderr


# ---------------------------------------------------------------------------
# --chapters 区间过滤
# ---------------------------------------------------------------------------


class TestChaptersRange:
    """`--chapters` 1-based 序号区间；范围外章节不派发（负例守护）."""

    def test_range_limits_dispatched_chapters(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(5))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--chapters", "1-2"])

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2)]
        for i in (3, 4, 5):
            assert _cid(i) not in fake.posted  # 负例：范围外不审计

    def test_comma_list_and_single_point(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(5))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--chapters", "2,4-5"])

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(2), _cid(4), _cid(5)]

    def test_out_of_range_positions_silently_dropped(self, cli_runner) -> None:
        """越界序号静默丢弃（不报错），仍处理命中的章节."""
        fake = _FakeClient(_chapters(3))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--chapters", "1-10"])

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2), _cid(3)]

    def test_invalid_range_exits_2(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(3))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--chapters", "5-3"])

        assert result.exit_code == 2, result.output
        assert "--chapters" in result.output  # 因区间非法而退 2（非「命令不存在」）
        assert fake.posted == []

    def test_no_matching_chapters_exits_1(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(2))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--chapters", "9-10"])

        assert result.exit_code == 1
        assert fake.posted == []


# ---------------------------------------------------------------------------
# --resume 断点续跑
# ---------------------------------------------------------------------------


class TestResume:
    """断点依据 = audit_logs 中该章存在**审计类**记录（#1562 收窄）.

    `audit_logs` 表被多模块共用 `severity_summary` 承载「动作语义」（F44 草稿生命周期
    `draft_saved`/`draft_confirmed`、agentic writer `auto_saved`/`run_completed` 等）——
    这些行同样 `run_status='completed'` 且可能带 `chapter_id`，**不是审计记录**。
    仅 F34 章节审计落库的计数摘要（`N error, M warnings, K info`）计入断点。
    """

    @staticmethod
    def _log(
        cid: str,
        run_status: str,
        *,
        severity_summary: str = "0 error, 0 warnings, 0 info",
        summary: str = "",
    ) -> dict:
        """构造一条 audit_logs 行（默认 = F34 审计记录形态）.

        默认 `severity_summary` 为 F34 审计计数格式；非审计行（F44 生命周期 / agentic
        动作语义）由调用方覆盖 `severity_summary`。
        """
        return {
            "id": _FakeClient._log_id(cid),
            "project_id": str(PID),
            "chapter_id": cid,
            "chapter_title": "x",
            "status": "pending",
            "run_status": run_status,
            "severity_summary": severity_summary,
            "summary": summary,
            "degraded": False,
            "note": "",
            "created_at": TS,
            "confirmed_at": None,
            "error": "",
        }

    @staticmethod
    def _lifecycle_log(cid: str | None, marker: str) -> dict:
        """构造 F44 生命周期 / 动作语义行（写作/转正链写入，非审计记录）.

        形态对齐 issue #1562 实测表：`severity_summary` 承载动作语义（`draft_saved` 行
        `chapter_id` 可为空，`draft_confirmed` 行带 `chapter_id`），`run_status='completed'`。
        """
        row = TestResume._log(cid or _cid(1), "completed", severity_summary=marker)
        row["chapter_id"] = cid
        row["summary"] = f"[agent:writer] {marker}"
        row["degraded"] = True
        return row

    def test_resume_skips_completed_chapters(self, cli_runner) -> None:
        """已完成（completed）章节不重复派发；failed 章节照跑."""
        fake = _FakeClient(
            _chapters(3),
            logs=[self._log(_cid(1), "completed"), self._log(_cid(2), "failed")],
        )
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(2), _cid(3)]  # 1 已完成跳过；2 是 failed → 重跑
        data = json.loads(result.stdout)["data"]
        assert data["skipped"] == 1
        assert [ch["chapter_id"] for ch in data["skipped_chapters"]] == [_cid(1)]

    def test_resume_queries_audit_logs_list(self, cli_runner) -> None:
        """--resume 的断点依据来自 GET /projects/{pid}/audit-logs（不新建进度表）."""
        fake = _FakeClient(_chapters(2), logs=[self._log(_cid(1), "completed")])
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"])

        assert result.exit_code == 0
        assert f"/projects/{PID}/audit-logs" in fake.get_paths
        assert fake.posted == [_cid(2)]

    def test_resume_all_done_exits_0_without_dispatch(self, cli_runner) -> None:
        fake = _FakeClient(
            _chapters(2),
            logs=[self._log(_cid(1), "completed"), self._log(_cid(2), "completed")],
        )
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == []
        assert json.loads(result.stdout)["data"]["skipped"] == 2

    def test_without_resume_completed_chapters_are_reaudited(self, cli_runner) -> None:
        """负例守护：不加 --resume 时已完成的章节仍照常派发."""
        fake = _FakeClient(_chapters(2), logs=[self._log(_cid(1), "completed")])
        result = _invoke_install(fake, ["batch", "-p", str(PID)])

        assert result.exit_code == 0
        assert fake.posted == [_cid(1), _cid(2)]


# ---------------------------------------------------------------------------
# --resume 断点判据收窄（#1562）——非审计行不得计为「已审计」
# ---------------------------------------------------------------------------


class TestResumeExcludesNonAuditRows:
    """`audit_logs` 混载 F44 生命周期/动作语义行 → 断点判据只认 F34 审计记录（#1562）."""

    def test_draft_confirmed_row_is_not_an_audit_record(self, cli_runner) -> None:
        """根因断言：仅存 draft_confirmed 行的章**从未审计** → --resume 必须实际审计.

        缺陷形态下 FAIL：旧判据只看 `run_status=='completed'` + `chapter_id` 非空，
        把「写作 + 转正」留下的 `draft_confirmed` 行当成已审计 → 该章被静默跳过
        （`audited=0` / `skipped=1`，`log_id` 为空）。
        """
        fake = _FakeClient(
            _chapters(1),
            logs=[
                TestResume._lifecycle_log(None, "draft_saved"),  # 未绑章的保存行
                TestResume._lifecycle_log(_cid(1), "draft_confirmed"),  # 转正行
            ],
        )
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1)]  # 必派发（缺陷形态：被跳过）
        data = json.loads(result.stdout)["data"]
        assert data["audited"] == 1
        assert data["skipped"] == 0
        assert data["chapters"][0]["log_id"] is not None  # 真审计了（三证之一）

    def test_first_resume_with_only_lifecycle_rows_skips_nothing(self, cli_runner) -> None:
        """首轮 --resume（只有草稿生命周期行、无任何审计记录）→ skipped=0（缺陷形态 FAIL）."""
        fake = _FakeClient(
            _chapters(3),
            logs=[
                TestResume._lifecycle_log(_cid(1), "draft_confirmed"),
                TestResume._lifecycle_log(_cid(2), "draft_confirmed"),
                TestResume._lifecycle_log(_cid(3), "draft_confirmed"),
            ],
        )
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2), _cid(3)]
        assert json.loads(result.stdout)["data"]["skipped"] == 0

    def test_agentic_writer_rows_are_not_audit_records(self, cli_runner) -> None:
        """同一根因类（sibling）：agentic writer 动作行（auto_saved/run_completed）亦非审计记录.

        这类行同样带 `chapter_id` + `run_status='completed'`（`severity_summary` 承载
        动作语义）——只排除 `draft_*` 的窄化过滤会漏掉它们，故判据必须正向认「审计记录」。
        """
        fake = _FakeClient(
            _chapters(2),
            logs=[
                TestResume._lifecycle_log(_cid(1), "auto_saved"),
                TestResume._lifecycle_log(_cid(1), "run_completed"),
                TestResume._lifecycle_log(_cid(2), "run_failed"),
            ],
        )
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2)]
        assert json.loads(result.stdout)["data"]["skipped"] == 0

    def test_genuine_audit_record_still_skipped(self, cli_runner) -> None:
        """守护：F34 审计记录（计数摘要格式）仍正确跳过 —— 收窄判据不误伤已完成章."""
        fake = _FakeClient(_chapters(2), logs=[TestResume._log(_cid(1), "completed")])
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--resume"], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(2)]
        assert json.loads(result.stdout)["data"]["skipped"] == 1


# ---------------------------------------------------------------------------
# 并发控制
# ---------------------------------------------------------------------------


class TestConcurrency:
    """默认串行（最多一章在 running）；--concurrency N 限并发."""

    def test_default_is_serial(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(4), poll_running=1)
        result = _invoke_install(fake, ["batch", "-p", str(PID)])

        assert result.exit_code == 0, result.output
        assert fake.max_inflight == 1

    def test_concurrency_two_bounds_inflight(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(4), poll_running=1)
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--concurrency", "2"])

        assert result.exit_code == 0, result.output
        assert 1 < fake.max_inflight <= 2  # 真并发（>1）且受限（<=2）

    def test_concurrency_below_one_exits_2(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(2))
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--concurrency", "0"])

        assert result.exit_code == 2, result.output
        assert "--concurrency" in result.output  # 因参数非法而退 2（非「命令不存在」）
        assert fake.posted == []


# ---------------------------------------------------------------------------
# 失败不中断 + 幂等复用
# ---------------------------------------------------------------------------


class TestFailurePolicy:
    """单章 run_status=failed → 不中断整批，记入失败清单."""

    def test_failed_chapter_does_not_abort_batch(self, cli_runner) -> None:
        fake = _FakeClient(_chapters(3), fail=(_cid(2),))
        result = _invoke_install(fake, ["batch", "-p", str(PID)], json_output=True)

        assert result.exit_code == 0, result.output
        assert fake.posted == [_cid(1), _cid(2), _cid(3)]  # 2 失败后仍跑 3
        data = json.loads(result.stdout)["data"]
        assert data["failed"] == 1
        assert data["audited"] == 2
        assert [f["chapter_id"] for f in data["failures"]] == [_cid(2)]
        assert "boom" in data["failures"][0]["error"]

    def test_reused_completed_record_skips_polling(self, cli_runner) -> None:
        """POST 幂等复用（202 status=completed）→ 不再轮询 /status，直接取明细."""
        fake = _FakeClient(_chapters(1), reuse_completed=(_cid(1),))
        result = _invoke_install(fake, ["batch", "-p", str(PID)])

        assert result.exit_code == 0, result.output
        assert not any(p.endswith("/status") for p in fake.get_paths)
        assert f"/audit-logs/{_FakeClient._log_id(_cid(1))}" in fake.get_paths


# ---------------------------------------------------------------------------
# 报告落盘
# ---------------------------------------------------------------------------


class TestReportOutput:
    """`--out PATH` → Markdown 写 PATH、JSON 写同主名 .json；省略 = 只打印 stdout."""

    def test_out_writes_markdown_and_json(self, cli_runner, tmp_path) -> None:
        fake = _FakeClient(
            _chapters(2), findings={_cid(1): [_finding("word_count", "info", "偏少")]}
        )
        out = tmp_path / "report.md"
        result = _invoke_install(fake, ["batch", "-p", str(PID), "--out", str(out)])

        assert result.exit_code == 0, result.output
        assert out.exists()
        md = out.read_text(encoding="utf-8")
        assert "## 按严重度归类" in md
        assert "第 1 章" in md

        js = tmp_path / "report.json"
        assert js.exists()
        data = json.loads(js.read_text(encoding="utf-8"))
        assert data["by_severity"]["info"] == 1

    def test_without_out_no_file_written(self, cli_runner, tmp_path, monkeypatch) -> None:
        """负例守护：省略 --out 时 cwd 不产生报告文件（避免污染仓库）."""
        fake = _FakeClient(_chapters(1))
        monkeypatch.chdir(tmp_path)
        result = _invoke_install(fake, ["batch", "-p", str(PID)])

        assert result.exit_code == 0, result.output
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# 命令注册
# ---------------------------------------------------------------------------


class TestBatchRegistration:
    """`inkflow audit batch` 是 audit 组的一级命令（与 check / chapter 同级）."""

    def test_batch_registered_under_audit_group(self, cli_runner) -> None:
        result = cli_runner.invoke(app, ["--help"], obj=CliContext(json_output=False))

        assert result.exit_code == 0
        assert "batch" in result.output
