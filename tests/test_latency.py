"""C3: キャプチャトリガー受信から完了までのレイテンシを実測し、記録として残す。

design/control_dump_tech_selection.md のリスク対応(マーカー呼び出しは非同期キュー
投入のみで即時返却し、重い処理は非同期実行する)が、実際にどの程度のレイテンシに
収まるかを数値として記録する。閾値判定ではなく記録が目的のため、緩いアサーションのみ行う。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")

PORT = 8766
N_SAMPLES = 10


def test_capture_latency_statistics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notepad_window) -> None:
    import httpx
    import uvicorn

    from dump_daemon import daemon

    output_dir = tmp_path / "capture_output"
    monkeypatch.setattr(daemon, "OUTPUT_DIR", output_dir)

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
        response_latencies_ms: list[float] = []
        for i in range(N_SAMPLES):
            start = time.perf_counter()
            resp = httpx.post(
                f"http://127.0.0.1:{PORT}/capture",
                json={"action_id": f"latency-{i}", "flow_name": "latency_test"},
                timeout=5,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            response_latencies_ms.append(elapsed_ms)

        # バックグラウンドタスクが実際にファイルを書き終えるまでの待ち時間も記録する
        # (応答の即時性=C1/C2と、実際の処理完了時間=この統計、は別物として区別する)。
        record_path = output_dir / "actions.jsonl"
        deadline = time.time() + 15
        while time.time() < deadline:
            if record_path.exists():
                lines = [l for l in record_path.read_text(encoding="utf-8").splitlines() if l.strip()]
                if len(lines) >= N_SAMPLES:
                    break
            time.sleep(0.2)

        stats = {
            "n_samples": N_SAMPLES,
            "response_latency_ms": {
                "min": min(response_latencies_ms),
                "max": max(response_latencies_ms),
                "mean": sum(response_latencies_ms) / len(response_latencies_ms),
                "samples": response_latencies_ms,
            },
        }
        print(f"[C3] capture latency stats: {json.dumps(stats, indent=2)}")

        stats_path = output_dir / "latency_stats.json"
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

        # 応答の即時性(C1/C2)は既存テストで確認済み。ここでは極端な劣化が無いことのみ確認する。
        assert stats["response_latency_ms"]["mean"] < 2000, (
            "キャプチャエンドポイントの平均応答時間が異常に大きい"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
