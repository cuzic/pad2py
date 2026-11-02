"""C1/C2/C3/C4: 常駐デーモン(FastAPI)のHTTP受信・非同期バックグラウンド処理の検証。"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")

PORT = 8765


@pytest.fixture
def running_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import uvicorn

    from dump_daemon import daemon

    monkeypatch.setattr(daemon, "OUTPUT_DIR", tmp_path / "capture_output")

    config = uvicorn.Config(daemon.app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        pytest.fail("デーモンが起動タイムアウト内に開始しなかった")

    try:
        yield daemon.OUTPUT_DIR
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_health_endpoint_responds(running_daemon) -> None:
    import httpx

    resp = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_capture_endpoint_returns_immediately(running_daemon, notepad_window) -> None:
    import httpx

    start = time.time()
    resp = httpx.post(
        f"http://127.0.0.1:{PORT}/capture",
        json={"action_id": "a1", "flow_name": "f1"},
        timeout=5,
    )
    elapsed = time.time() - start

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}
    assert elapsed < 1.0, "レスポンスが即時返却になっていない(重い処理がブロッキングしている可能性)"


def test_capture_eventually_writes_action_record_and_validates_schema(
    running_daemon, notepad_window
) -> None:
    import httpx
    import jsonschema

    resp = httpx.post(
        f"http://127.0.0.1:{PORT}/capture",
        json={"action_id": "a2", "flow_name": "f1"},
        timeout=5,
    )
    assert resp.status_code == 200

    record_path = running_daemon / "actions.jsonl"
    record = None
    for _ in range(50):
        if record_path.exists():
            lines = [l for l in record_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            matching = [json.loads(l) for l in lines if json.loads(l)["action_uid"] == "a2"]
            if matching:
                record = matching[-1]
                break
        time.sleep(0.2)

    assert record is not None, "actions.jsonl にa2の記録が書き込まれなかった(タイムアウト)"
    assert Path(record["ui_tree_ref"]).exists()

    # D2相当: 生成されたUIツリーがschemaに適合するか
    schema_dir = Path(__file__).resolve().parents[1] / "design" / "schemas"
    tree_schema = json.loads((schema_dir / "ui_tree_snapshot.schema.json").read_text(encoding="utf-8"))
    tree_instance = json.loads(Path(record["ui_tree_ref"]).read_text(encoding="utf-8"))
    jsonschema.validate(tree_instance, tree_schema)
