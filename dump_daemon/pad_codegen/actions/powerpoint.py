"""`PowerPoint.*`のcodegen。

`pad_action_lib.powerpoint_actions`へ委譲する。知見80では、action_id文字列はPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`で「アクションが存在する」ことまでは
確認していたが、これはアクション**グループ**のAutomationIdであり、知見155-157
(Excel/PDF/Word)と同じ`ActionSelectorBase`一括列挙監査を知見158でPowerPointにも
適用した結果、`AddPowerPointSlide`/`ClosePowerPoint`/`DeletePowerPointSlide`/
`LaunchPowerPoint`/`ReadFromPowerPoint`/`SavePowerPoint`/`WriteToPowerPoint`の
7グループには実際には兄弟セレクタがあり、DSL上の真のaction_idは
`PowerPoint.<グループ>.<ActionName>`という3セグメント形式だと判明した(いずれも
`[Action(...)]`に`Id`属性の上書きが無いため中間セグメント=クラス名自体は従来通り
正しかったが、**第3セグメントが欠けていたため実際のDSLでは一度もマッチしなかった**、
知見155-157と同種の潜在バグ、知見158で発見・修正)。`MovePowerPointSlide`は兄弟
セレクタが存在せず、既存のフラットな形式のままで正しい。

`Instance`(`PowerPointInstanceHandle`への参照)は`excel.py`/`word.py`の`Instance`と同じく、
PAD側では不透明な参照だがPythonコード生成の観点では他の変数参照と同じ(特別な結線は不要)。
`MovePowerPointSlide`の`SourceInstance`/`DestinationInstance`も同様。

ライブPowerPoint COM専用の機能(`AttachToRunningPowerPoint`・クロスプレゼンテーションの
コピー&ペースト/移動・レガシー形式への変換保存)は`pad_action_lib.powerpoint_actions`側で
最初からスコープ外(docs-local/pad_powerpoint_findings.md)——クロスプレゼンテーション移動は
Python側が実行時に`NotImplementedError`を投げる(`SourceInstance`/`DestinationInstance`は
常に変数参照でコード生成時点では判定できないため、呼び出し自体は生成し実行時の判定に委ねる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("PowerPoint."):
        return None
    prefix = INDENT * indent
    p = node.params

    # 知見158: `LaunchPowerPoint`の兄弟セレクタ2件。
    if action_id == "PowerPoint.LaunchPowerPoint.Launch":
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.launch_power_point("
            f"mode='NewPresentation', path=None, read_only=False)"
        ]

    if action_id == "PowerPoint.LaunchPowerPoint.LaunchAndOpen":
        path = safe_render(p.get("Path"))
        read_only = safe_render(p.get("ReadOnly", False))
        if path is None or read_only is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.launch_power_point("
            f"mode='StoredPresentation', path={path}, read_only={read_only})"
        ]

    # 知見158: `SavePowerPoint`の兄弟セレクタ2件。
    if action_id == "PowerPoint.SavePowerPoint.Save":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}powerpoint_actions.save_power_point({instance}, save_mode='Save', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "PowerPoint.SavePowerPoint.SaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}powerpoint_actions.save_power_point({instance}, save_mode='SaveAs', "
            f"document_format='FromExtension', document_path={document_path})"
        ]

    # 知見158: `ClosePowerPoint`の兄弟セレクタ3件。
    if action_id == "PowerPoint.ClosePowerPoint.Close":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}powerpoint_actions.close_power_point({instance}, close_mode='DoNotSave', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "PowerPoint.ClosePowerPoint.CloseAndSave":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}powerpoint_actions.close_power_point({instance}, close_mode='Save', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "PowerPoint.ClosePowerPoint.CloseAndSaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}powerpoint_actions.close_power_point({instance}, close_mode='SaveAs', "
            f"document_format='FromExtension', document_path={document_path})"
        ]

    # 知見158: `ReadFromPowerPoint`の兄弟セレクタ2件(`ReadMode`は`WholePresentation`/
    # `Slides`で固定)。
    if action_id == "PowerPoint.ReadFromPowerPoint.Read":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.read_from_power_point("
            f"{instance}, read_mode='WholePresentation', slides='1')"
        ]

    if action_id == "PowerPoint.ReadFromPowerPoint.ReadSlides":
        instance = safe_render(p.get("Instance"))
        slides = safe_render(p.get("Slides", "1"))
        if instance is None or slides is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.read_from_power_point("
            f"{instance}, read_mode='Slides', slides={slides})"
        ]

    # 知見158: `WriteToPowerPoint`の兄弟セレクタ3件(`WriteMode`は`FirstSlide`/`LastSlide`/
    # `AtPosition`で固定)。
    _POWERPOINT_WRITE_MODE = {
        "PowerPoint.WriteToPowerPoint.WriteToFirstSlide": "FirstSlide",
        "PowerPoint.WriteToPowerPoint.WriteToLastSlide": "LastSlide",
    }
    write_mode = _POWERPOINT_WRITE_MODE.get(action_id)
    if write_mode is not None:
        instance = safe_render(p.get("Instance"))
        text = safe_render(p.get("Text"))
        append_new_line = safe_render(p.get("AppendNewLine", False))
        if None in (instance, text, append_new_line):
            return None
        return [
            f"{prefix}powerpoint_actions.write_to_power_point({instance}, {text}, "
            f"append_new_line={append_new_line}, write_mode={write_mode!r}, slide_position=1)"
        ]

    if action_id == "PowerPoint.WriteToPowerPoint.WriteToSlideAtPosition":
        instance = safe_render(p.get("Instance"))
        text = safe_render(p.get("Text"))
        append_new_line = safe_render(p.get("AppendNewLine", False))
        slide_position = safe_render(p.get("SlidePosition", 1))
        if None in (instance, text, append_new_line, slide_position):
            return None
        return [
            f"{prefix}powerpoint_actions.write_to_power_point({instance}, {text}, "
            f"append_new_line={append_new_line}, write_mode='AtPosition', "
            f"slide_position={slide_position})"
        ]

    # 知見158: `AddPowerPointSlide`の兄弟セレクタ3件(`AddSlidePosition`は`FirstSlide`/
    # `LastSlide`/`AtPosition`で固定)。
    _POWERPOINT_ADD_SLIDE_POSITION = {
        "PowerPoint.AddPowerPointSlide.AddSlideAsFirst": "FirstSlide",
        "PowerPoint.AddPowerPointSlide.AddSlideAsLast": "LastSlide",
    }
    add_slide_position = _POWERPOINT_ADD_SLIDE_POSITION.get(action_id)
    if add_slide_position is not None:
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.add_power_point_slide("
            f"{instance}, add_slide_position={add_slide_position!r}, slide_position=1)"
        ]

    if action_id == "PowerPoint.AddPowerPointSlide.AddSlideAtPosition":
        instance = safe_render(p.get("Instance"))
        slide_position = safe_render(p.get("SlidePosition", 1))
        if instance is None or slide_position is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.add_power_point_slide("
            f"{instance}, add_slide_position='AtPosition', slide_position={slide_position})"
        ]

    # 知見158: `DeletePowerPointSlide`の兄弟セレクタ3件(`DeleteSlidePosition`は
    # `FirstSlide`/`LastSlide`/`AtPosition`で固定)。
    _POWERPOINT_DELETE_SLIDE_POSITION = {
        "PowerPoint.DeletePowerPointSlide.DeleteSlideFirst": "FirstSlide",
        "PowerPoint.DeletePowerPointSlide.DeleteSlideLast": "LastSlide",
    }
    delete_slide_position = _POWERPOINT_DELETE_SLIDE_POSITION.get(action_id)
    if delete_slide_position is not None:
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}powerpoint_actions.delete_power_point_slide({instance}, "
            f"delete_slide_position={delete_slide_position!r}, slide_position=1)"
        ]

    if action_id == "PowerPoint.DeletePowerPointSlide.DeleteSlideAtPosition":
        instance = safe_render(p.get("Instance"))
        slide_position = safe_render(p.get("SlidePosition", 1))
        if instance is None or slide_position is None:
            return None
        return [
            f"{prefix}powerpoint_actions.delete_power_point_slide({instance}, "
            f"delete_slide_position='AtPosition', slide_position={slide_position})"
        ]

    if action_id == "PowerPoint.MovePowerPointSlide":
        source = safe_render(p.get("SourceInstance"))
        destination = safe_render(p.get("DestinationInstance"))
        if source is None or destination is None:
            return None
        source_position = safe_render(p.get("SourceSlidePosition", 1))
        destination_position = safe_render(p.get("DestinationSlidePosition", 1))
        if source_position is None or destination_position is None:
            return None
        return [
            f"{prefix}powerpoint_actions.move_power_point_slide({source}, {source_position}, "
            f"{destination}, {destination_position})"
        ]

    return None
