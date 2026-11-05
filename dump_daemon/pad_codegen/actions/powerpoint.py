"""`PowerPoint.*`のcodegen。

`pad_action_lib.powerpoint_actions`へ委譲する。知見80で、action_id文字列は全てPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`プロパティを直接読んで実機確認済み
(知見77と同じ経路)。パラメータ名は実機UIではなく、各`*Action`クラスの`InputArgument`/
`OutputArgument`属性宣言(ilspycmdによるdecompile、docs-local/pad_powerpoint_findings.md)
から読み取った値。

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
from ._support import enum_last, safe_render


def _enum_arg(p: dict, name: str, default: str) -> str | None:
    """enumパラメータの値(省略時は`default`)を`repr()`済みのPython式として返す。"""
    if name in p:
        value = enum_last(p.get(name))
        if value is None:
            return None
        return repr(value)
    return repr(default)


def _optional_path_arg(p: dict, name: str) -> str | None:
    """`FileObject`系のオプション引数(省略時はPythonの`None`リテラル)を返す。"""
    if name in p:
        return safe_render(p.get(name))
    return "None"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("PowerPoint."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "PowerPoint.LaunchPowerPoint":
        if not node.output_var:
            return None
        mode = _enum_arg(p, "LaunchPowerPointMode", "NewPresentation")
        path = _optional_path_arg(p, "Path")
        read_only = safe_render(p.get("ReadOnly", False))
        if mode is None or path is None or read_only is None:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.launch_power_point("
            f"mode={mode}, path={path}, read_only={read_only})"
        ]

    if action_id == "PowerPoint.SavePowerPoint":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        save_mode = _enum_arg(p, "SaveMode", "Save")
        document_format = _enum_arg(p, "DocumentFormat", "FromExtension")
        document_path = _optional_path_arg(p, "DocumentPath")
        if save_mode is None or document_format is None or document_path is None:
            return None
        return [
            f"{prefix}powerpoint_actions.save_power_point({instance}, save_mode={save_mode}, "
            f"document_format={document_format}, document_path={document_path})"
        ]

    if action_id == "PowerPoint.ClosePowerPoint":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        close_mode = _enum_arg(p, "CloseMode", "DoNotSave")
        document_format = _enum_arg(p, "DocumentFormat", "FromExtension")
        document_path = _optional_path_arg(p, "DocumentPath")
        if close_mode is None or document_format is None or document_path is None:
            return None
        return [
            f"{prefix}powerpoint_actions.close_power_point({instance}, close_mode={close_mode}, "
            f"document_format={document_format}, document_path={document_path})"
        ]

    if action_id == "PowerPoint.ReadFromPowerPoint":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        read_mode = _enum_arg(p, "ReadMode", "WholePresentation")
        slides = safe_render(p.get("Slides", "1"))
        if read_mode is None or slides is None:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.read_from_power_point("
            f"{instance}, read_mode={read_mode}, slides={slides})"
        ]

    if action_id == "PowerPoint.WriteToPowerPoint":
        instance = safe_render(p.get("Instance"))
        text = safe_render(p.get("Text"))
        if instance is None or text is None:
            return None
        write_mode = _enum_arg(p, "WriteMode", "FirstSlide")
        slide_position = safe_render(p.get("SlidePosition", 1))
        append_new_line = safe_render(p.get("AppendNewLine", False))
        if write_mode is None or slide_position is None or append_new_line is None:
            return None
        return [
            f"{prefix}powerpoint_actions.write_to_power_point({instance}, {text}, "
            f"append_new_line={append_new_line}, write_mode={write_mode}, "
            f"slide_position={slide_position})"
        ]

    if action_id == "PowerPoint.AddPowerPointSlide":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        add_slide_position = _enum_arg(p, "AddSlidePosition", "LastSlide")
        slide_position = safe_render(p.get("SlidePosition", 1))
        if add_slide_position is None or slide_position is None:
            return None
        return [
            f"{prefix}{node.output_var} = powerpoint_actions.add_power_point_slide("
            f"{instance}, add_slide_position={add_slide_position}, "
            f"slide_position={slide_position})"
        ]

    if action_id == "PowerPoint.DeletePowerPointSlide":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        delete_slide_position = _enum_arg(p, "DeleteSlidePosition", "LastSlide")
        slide_position = safe_render(p.get("SlidePosition", 1))
        if delete_slide_position is None or slide_position is None:
            return None
        return [
            f"{prefix}powerpoint_actions.delete_power_point_slide({instance}, "
            f"delete_slide_position={delete_slide_position}, slide_position={slide_position})"
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
