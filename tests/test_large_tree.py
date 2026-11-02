"""D3/D4: より要素数の多い実アプリ(エクスプローラー)に対する、深いネスト・欠損パターンへの
頑健性検証。Notepadは要素数が少なく、再帰的スキーマ検証の実質的なストレステストにならないため、
多数のファイルを含むフォルダーを開いたエクスプローラーウィンドウを対象にする。

副産物として、UIA仮想化リスト(研究ノート 04_selector_mapping.md で指摘されていた既知の
落とし穴)が実際にこのCI環境でも観測されるかどうかの参考情報も記録する。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

from dump_daemon.uia_capture import dump_uia_tree, flatten_element_ids

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")

N_FILES = 80
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "design" / "schemas"


def test_dump_uia_tree_on_large_explorer_window_validates_schema(tmp_path: Path) -> None:
    unique_name = f"pad2py_stress_{int(time.time())}"
    stress_dir = tmp_path / unique_name
    stress_dir.mkdir()
    for i in range(N_FILES):
        (stress_dir / f"file_{i:03d}.txt").write_text("x", encoding="utf-8")

    proc = subprocess.Popen(["explorer.exe", str(stress_dir)])
    try:
        from pywinauto import Desktop

        window = None
        pattern = re.escape(unique_name)
        for _ in range(40):
            time.sleep(0.5)
            try:
                candidates = Desktop(backend="uia").windows(title_re=f".*{pattern}.*")
            except Exception:
                candidates = []
            if candidates:
                window = candidates[0]
                break

        if window is None:
            pytest.skip(f"エクスプローラーウィンドウ({unique_name})をタイムアウト内に検出できなかった")

        tree = dump_uia_tree(window, max_depth=30)
        ids = flatten_element_ids(tree)
        element_count = len(ids)

        print(f"[D3/D4] Explorer window element count: {element_count} (配置ファイル数: {N_FILES})")
        # 仮想化リストにより画面外の行がツリーに実体化されない可能性があるため、
        # N_FILES との厳密な一致は要求しない。再帰処理が完走し、要素が一定数取得できる
        # ことと、衝突の無いIDが振られることを確認する。
        assert element_count > 5, "取得できた要素数が少なすぎる(ウィンドウ取得自体に失敗している可能性)"
        assert len(ids) == len(set(ids)), "大規模ツリーでelement_idの衝突が発生した"

        tree_schema = json.loads((SCHEMA_DIR / "ui_tree_snapshot.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(
            {"captured_at": "2026-11-02T00:00:00Z", "capture_mode": "UIA", "root": tree},
            tree_schema,
        )

        if element_count < N_FILES:
            print(
                f"[D3/D4] 参考情報: 配置したファイル数({N_FILES})よりツリー内要素数が少ない"
                f"({element_count})。UIA仮想化リストにより画面外の行が実体化されていない可能性がある"
                "(research_notes/.../04_selector_mapping.md で指摘されていた既知の落とし穴)。"
            )
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        # 開いたエクスプローラーウィンドウ自体も個別に閉じる(explorer.exeのkillでは閉じない場合がある)
        try:
            from pywinauto import Desktop

            for w in Desktop(backend="uia").windows(title_re=f".*{re.escape(unique_name)}.*"):
                try:
                    w.close_window() if hasattr(w, "close_window") else None
                except Exception:
                    pass
        except Exception:
            pass
