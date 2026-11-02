"""常駐デーモン(検証項目 C1/C2/C3/C4)。

design/control_dump_tech_selection.md の「アクティブマーカー + 常駐デーモン」構成に対応する。
PAD側の『Run Python script』アクションから呼ばれる極薄クライアントが /capture を
HTTP POSTで叩くと、即座にレスポンスを返しつつ、重い処理(UIAツリー走査+スクリーンショット)を
バックグラウンドタスクとして非同期実行する。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from dump_daemon.screenshot import capture_region
from dump_daemon.uia_capture import dump_uia_tree

app = FastAPI()

# モジュール属性として持たせ、テストから monkeypatch で差し替えられるようにする。
OUTPUT_DIR = Path("capture_output")
_capture_count = 0


class CaptureRequest(BaseModel):
    action_id: str
    flow_name: str


def _get_foreground_window() -> Any | None:
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows()
        return windows[0] if windows else None
    except Exception:
        return None


def _do_capture(action_id: str, flow_name: str) -> None:
    global _capture_count
    idx = _capture_count
    _capture_count += 1

    # ir_trace.schema.json / ui_tree_snapshot.schema.json は timestamp を
    # format: date-time (ISO 8601文字列) で要求するため、UNIX epoch floatではなく
    # ISO文字列として記録する。
    ts = datetime.now(timezone.utc).isoformat()
    window = _get_foreground_window()
    tree = dump_uia_tree(window) if window is not None else None

    tree_path = OUTPUT_DIR / "ui_trees" / f"{idx:06d}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(
        json.dumps({"captured_at": ts, "capture_mode": "UIA", "root": tree}, ensure_ascii=False),
        encoding="utf-8",
    )

    shot_path: Path | None = OUTPUT_DIR / "screenshots" / f"{idx:06d}.png"
    try:
        capture_region(shot_path)
    except Exception:
        shot_path = None

    record_path = OUTPUT_DIR / "actions.jsonl"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "action_uid": action_id,
        "flow_name": flow_name,
        "timestamp": ts,
        "ui_tree_ref": str(tree_path),
        "screenshot_ref": str(shot_path) if shot_path else None,
    }
    with record_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@app.post("/capture")
async def capture(req: CaptureRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(_do_capture, req.action_id, req.flow_name)
    return {"status": "queued"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
