"""D1/D3/D4: 実キャプチャデータがIR/UIツリーの両JSON Schemaに適合するかの検証。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "design" / "schemas"


@pytest.fixture(scope="module")
def tree_schema() -> dict:
    return json.loads((SCHEMA_DIR / "ui_tree_snapshot.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ir_schema() -> dict:
    return json.loads((SCHEMA_DIR / "ir_trace.schema.json").read_text(encoding="utf-8"))


def test_real_uia_capture_validates_against_tree_schema(notepad_window, tree_schema) -> None:
    from dump_daemon.uia_capture import dump_uia_tree

    root = dump_uia_tree(notepad_window)
    instance = {
        "captured_at": "2026-11-02T00:00:00Z",
        "capture_mode": "UIA",
        "root": root,
    }
    jsonschema.validate(instance, tree_schema)


def test_real_capture_wrapped_as_action_record_validates_against_ir_schema(
    notepad_window, ir_schema
) -> None:
    from dump_daemon.uia_capture import dump_uia_tree

    root = dump_uia_tree(notepad_window)
    ir_instance = {
        "schema_version": "0.1.0",
        "trace_id": "ci-verification-trace",
        "flow_meta": {
            "flow_name": "ci_smoke_test",
            "power_fx_enabled": False,
            "captured_at": "2026-11-02T00:00:00Z",
        },
        "actions": [
            {
                "action_uid": "ci-a1",
                "sequence_index": 0,
                "action_type": "UIAutomation.GetDetails",
                "block": None,
                "params": {},
                "output_var": None,
                "timestamp": "2026-11-02T00:00:01Z",
                "target_element": None,
                "screen_state_before": {
                    "ui_tree_ref": "ui_trees/000000.json",
                    "screenshot_ref": None,
                    "alt_text": "Notepad実機キャプチャ(CI検証)",
                    "active_window": {
                        "title": "Notepad",
                        "process_name": "notepad.exe",
                        "handle": notepad_window.handle,
                    },
                    "captured_via": "active_marker",
                },
                "screen_state_after": None,
                "raw_source": None,
            }
        ],
    }
    jsonschema.validate(ir_instance, ir_schema)

    # ツリー本体も個別にスキーマ適合を確認(D3: 深いネストでも完走するか)
    tree_schema_data = json.loads((SCHEMA_DIR / "ui_tree_snapshot.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate({"captured_at": "2026-11-02T00:00:00Z", "root": root}, tree_schema_data)
