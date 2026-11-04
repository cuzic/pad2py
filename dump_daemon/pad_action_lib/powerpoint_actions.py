"""`PowerPoint.Actions`のロジック層。

実機の`PowerPointActions`は*ライブの*PowerPoint COMインスタンス(`LaunchPowerPoint`/
`AttachToRunningPowerPoint`/インスタンスハンドル)を操作する設計——`python-pptx`
(.pptxファイルをオフラインで直接編集するライブラリ、COM/ライブアプリ不使用)では
忠実に再現できない。したがってこの層は「値の読み書きと基本的なスライド構造操作」に
スコープを絞り、COM専用の機能(実行中インスタンスへのアタッチ、クロスプレゼンテーション
のスライドコピー/移動)は明示的に`NotImplementedError`とする。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation as _Presentation
from pptx.presentation import Presentation as PresentationType
from pptx.util import Pt

from .errors import PadActionError


class LaunchPowerPointError(PadActionError):
    pass


class LaunchPowerPointFileNotFoundError(PadActionError):
    pass


class LaunchPowerPointInvalidFileTypeError(PadActionError):
    pass


class ClosePowerPointError(PadActionError):
    pass


class SavePowerPointError(PadActionError):
    pass


class SavePowerPointInstanceNullError(PadActionError):
    pass


class SavePowerPointFormatMismatchError(PadActionError):
    pass


class SavePowerPointUnsupportedExtensionError(PadActionError):
    pass


class SavePowerPointUnsupportedFormatError(PadActionError):
    pass


class ReadPowerPointError(PadActionError):
    pass


class WritePowerPointError(PadActionError):
    pass


class WritePowerPointInvalidSlidePositionError(PadActionError):
    pass


class WritePowerPointNoSlidesError(PadActionError):
    pass


class AddPowerPointSlideError(PadActionError):
    pass


class AddPowerPointSlideInvalidPositionError(PadActionError):
    pass


class DeletePowerPointSlideError(PadActionError):
    pass


class DeletePowerPointSlideInvalidPositionError(PadActionError):
    pass


class DeletePowerPointSlideNoSlidesError(PadActionError):
    pass


class MoveSlideError(PadActionError):
    pass


class MoveSlideInvalidSourcePositionError(PadActionError):
    pass


class MoveSlideInvalidDestinationPositionError(PadActionError):
    pass


class MoveSlideSourceNoSlidesError(PadActionError):
    pass


# 実機は.pptx/.pptm/.ppt/.potx/.potm/.pot/.ppsx/.ppsm/.pps/.odpの10種を開けるが、
# python-pptxが実際に展開できるのはOOXML zipコンテナ(.pptx/.pptm)のみ。
OPENABLE_EXTENSIONS = (".pptx", ".pptm")

# PowerPointFormat列挙体(実機は11種、FromExtensionは拡張子から自動判定)。
_FORMAT_EXTENSIONS = {
    "PPTX": ".pptx",
    "PPTM": ".pptm",
    "PPT": ".ppt",
    "PDF": ".pdf",
    "XPS": ".xps",
    "POTX": ".potx",
    "POTM": ".potm",
    "PPSX": ".ppsx",
    "PPSM": ".ppsm",
    "ODP": ".odp",
}
_SAVEABLE_EXTENSIONS = set(_FORMAT_EXTENSIONS.values())
# python-pptxが実際に書き出せるのはOOXML zipコンテナ(.pptx/.pptm)のみ。
_WRITABLE_EXTENSIONS = {".pptx", ".pptm"}

_BLANK_LAYOUT_INDEX = 6  # python-pptxの既定テンプレートで"Blank"レイアウトに対応するインデックス。

_SLIDE_RANGE_RE = re.compile(r"^\s*(\d+\s*(-\s*\d+)?\s*)(,\s*\d+\s*(-\s*\d+)?\s*)*,?\s*$")
_SLIDE_RANGE_ITEM_RE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


@dataclass
class PowerPointInstanceHandle:
    """不透明な「インスタンス」ハンドル(実機ではCOMオブジェクト参照、ここでは`Presentation`)。"""

    presentation: PresentationType
    path: str | None = None


def launch_power_point(
    mode: str = "NewPresentation", path: str | None = None, read_only: bool = False
) -> PowerPointInstanceHandle:
    # `read_only`はpython-pptxに対応概念が無く無視する(保存時の宛先指定で運用上代替する)。
    if mode == "NewPresentation":
        return PowerPointInstanceHandle(presentation=_Presentation())
    if mode != "StoredPresentation":
        raise ValueError(f"Unknown LaunchPowerPointMode: {mode!r}")
    if not path:
        raise LaunchPowerPointError("Path is required when mode is StoredPresentation")
    p = Path(path)
    if not p.is_file():
        raise LaunchPowerPointFileNotFoundError(str(path))
    if p.suffix.lower() not in OPENABLE_EXTENSIONS:
        raise LaunchPowerPointInvalidFileTypeError(
            f"{path}: only {', '.join(OPENABLE_EXTENSIONS)} are supported here "
            "(python-pptx cannot open legacy binary .ppt/.pot/.pps or OpenDocument .odp)"
        )
    try:
        presentation = _Presentation(str(p))
    except Exception as exc:
        raise LaunchPowerPointError(str(exc)) from exc
    return PowerPointInstanceHandle(presentation=presentation, path=str(p))


def _resolve_save_extension(document_format: str, document_path: str | None) -> str:
    if document_format == "FromExtension":
        if not document_path:
            raise SavePowerPointUnsupportedExtensionError("DocumentPath is required")
        ext = Path(document_path).suffix.lower()
        if ext not in _SAVEABLE_EXTENSIONS:
            raise SavePowerPointUnsupportedExtensionError(
                f"{ext or '(none)'}: not one of {sorted(_SAVEABLE_EXTENSIONS)}"
            )
        return ext
    try:
        expected = _FORMAT_EXTENSIONS[document_format]
    except KeyError as exc:
        raise SavePowerPointUnsupportedFormatError(f"Unknown PowerPointFormat: {document_format!r}") from exc
    actual = Path(document_path).suffix.lower() if document_path else ""
    if actual != expected:
        raise SavePowerPointFormatMismatchError(
            f"path extension {actual or '(none)'!r} does not match format {document_format!r} "
            f"(expected {expected!r})"
        )
    return expected


def save_power_point(
    instance: PowerPointInstanceHandle,
    save_mode: str = "Save",
    document_format: str = "FromExtension",
    document_path: str | None = None,
) -> None:
    if instance is None:
        raise SavePowerPointInstanceNullError("instance is None")
    if save_mode == "Save":
        if not instance.path:
            raise SavePowerPointError("Save requires the presentation to have been opened from a path")
        instance.presentation.save(instance.path)
        return
    if save_mode != "SaveAs":
        raise ValueError(f"Unknown SavePowerPointMode: {save_mode!r}")
    if not document_path:
        raise SavePowerPointError("DocumentPath is required for SaveAs")
    ext = _resolve_save_extension(document_format, document_path)
    if ext not in _WRITABLE_EXTENSIONS:
        raise NotImplementedError(
            f"saving as {ext} requires a format conversion this layer does not implement "
            "(python-pptx can only write .pptx/.pptm); extension/format validation above "
            "already matches the real PAD behavior"
        )
    instance.presentation.save(document_path)
    instance.path = document_path


def close_power_point(
    instance: PowerPointInstanceHandle,
    close_mode: str = "DoNotSave",
    document_format: str = "FromExtension",
    document_path: str | None = None,
) -> None:
    if instance is None:
        raise ClosePowerPointError("instance is None")
    if close_mode == "DoNotSave":
        return
    if close_mode == "Save":
        save_power_point(instance, "Save")
        return
    if close_mode == "SaveAs":
        save_power_point(instance, "SaveAs", document_format, document_path)
        return
    raise ValueError(f"Unknown ClosePowerPointMode: {close_mode!r}")


def _parse_slide_range(spec: str, slide_count: int) -> list[int]:
    if not _SLIDE_RANGE_RE.match(spec):
        raise ReadPowerPointError(f"invalid slide range syntax: {spec!r}")
    positions: list[int] = []
    for match in _SLIDE_RANGE_ITEM_RE.finditer(spec):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) is not None else None
        if end is not None:
            if start > end:
                raise ReadPowerPointError(f"range start {start} greater than end {end}")
            if start < 1:
                raise ReadPowerPointError(f"invalid slide number: {start}")
            end = min(end, slide_count)  # 終了側はスライド数に黙ってクランプする
            positions.extend(range(start, end + 1))
        else:
            if start < 1:
                raise ReadPowerPointError(f"invalid slide number: {start}")
            if start <= slide_count:  # 単一番号がスライド数超過なら黙ってスキップ(非対称)
                positions.append(start)
    return positions


def _slide_text(slide) -> str:
    parts = []
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text:
            parts.append(shape.text_frame.text)
    # 実機はEnvironment.NewLine("\r\n")でAppendLineするが、この層は"\n"のみを使う
    # (python-pptxが"\r"をXML上"_x000D_"というリテラルでエスケープしてしまう問題を回避)。
    return "".join(p + "\n" for p in parts)


def read_from_power_point(
    instance: PowerPointInstanceHandle, read_mode: str = "WholePresentation", slides: str = "1"
) -> str:
    prs = instance.presentation
    if read_mode == "WholePresentation":
        return "".join(_slide_text(slide) for slide in prs.slides)
    if read_mode != "Slides":
        raise ValueError(f"Unknown ReadPowerPointMode: {read_mode!r}")
    positions = _parse_slide_range(slides, len(prs.slides))
    return "".join(_slide_text(prs.slides[p - 1]) for p in positions)


def _resolve_write_target(write_mode: str, slide_position: int, slide_count: int) -> int:
    if slide_count == 0:
        raise WritePowerPointNoSlidesError("presentation has no slides")
    if write_mode == "FirstSlide":
        return 1
    if write_mode == "LastSlide":
        return slide_count
    if write_mode == "AtPosition":
        if slide_position < 1 or slide_position > slide_count:
            raise WritePowerPointInvalidSlidePositionError(
                f"{slide_position} not in [1, {slide_count}]"
            )
        return slide_position
    raise ValueError(f"Unknown WritePowerPointMode: {write_mode!r}")


def write_to_power_point(
    instance: PowerPointInstanceHandle,
    text: str,
    append_new_line: bool = False,
    write_mode: str = "FirstSlide",
    slide_position: int = 1,
) -> int:
    prs = instance.presentation
    target = _resolve_write_target(write_mode, slide_position, len(prs.slides))
    slide = prs.slides[target - 1]
    shape = next((s for s in slide.shapes if s.has_text_frame), None)
    if shape is None:
        shape = slide.shapes.add_textbox(Pt(50), Pt(50), Pt(600), Pt(400))
    text_frame = shape.text_frame
    existing = text_frame.text
    if append_new_line and existing:
        text_frame.text = existing + "\n" + text
    else:
        text_frame.text = existing + text
    return target


def _sld_id_list(prs: PresentationType):
    return prs.slides._sldIdLst  # noqa: SLF001 - python-pptxに公開APIが無いための既知の回避策


def _reorder_slide(prs: PresentationType, old_index: int, new_index: int) -> None:
    id_list = _sld_id_list(prs)
    items = list(id_list)
    id_list.remove(items[old_index])
    id_list.insert(new_index, items[old_index])


def _delete_slide_at(prs: PresentationType, index: int) -> None:
    # `_sldIdLst`から参照を外すだけで、スライド本体のXMLパートは孤立したまま
    # パッケージに残る(実害は無いが完全なクリーンアップではない、未実装)。
    id_list = _sld_id_list(prs)
    items = list(id_list)
    id_list.remove(items[index])


def add_power_point_slide(
    instance: PowerPointInstanceHandle, add_slide_position: str = "LastSlide", slide_position: int = 1
) -> int:
    prs = instance.presentation
    count = len(prs.slides)
    if add_slide_position == "FirstSlide":
        target = 1
    elif add_slide_position == "LastSlide":
        target = count + 1
    elif add_slide_position == "AtPosition":
        target = slide_position
        if target < 1 or target > count + 1:
            raise AddPowerPointSlideInvalidPositionError(f"{target} not in [1, {count + 1}]")
    else:
        raise ValueError(f"Unknown AddSlidePosition: {add_slide_position!r}")
    layout = prs.slide_layouts[_BLANK_LAYOUT_INDEX]
    prs.slides.add_slide(layout)  # 常に末尾に追加されるので、目的の位置へ並べ替える
    _reorder_slide(prs, count, target - 1)
    return target


def delete_power_point_slide(
    instance: PowerPointInstanceHandle, delete_slide_position: str = "LastSlide", slide_position: int = 1
) -> None:
    prs = instance.presentation
    count = len(prs.slides)
    if count == 0:
        raise DeletePowerPointSlideNoSlidesError("presentation has no slides")
    if delete_slide_position == "FirstSlide":
        target = 1
    elif delete_slide_position == "LastSlide":
        target = count
    elif delete_slide_position == "AtPosition":
        target = slide_position
        if target < 1 or target > count:
            raise DeletePowerPointSlideInvalidPositionError(f"{target} not in [1, {count}]")
    else:
        raise ValueError(f"Unknown DeleteSlidePosition: {delete_slide_position!r}")
    _delete_slide_at(prs, target - 1)


def move_power_point_slide(
    source: PowerPointInstanceHandle,
    source_slide_position: int,
    destination: PowerPointInstanceHandle,
    destination_slide_position: int,
) -> None:
    if source.presentation is not destination.presentation:
        raise NotImplementedError(
            "cross-presentation slide move relies on COM-level Copy/Paste fidelity; "
            "not approximable with python-pptx (same reasoning as CopyPastePowerPointSlide)"
        )
    prs = source.presentation
    count = len(prs.slides)
    if count == 0:
        raise MoveSlideSourceNoSlidesError("source presentation has no slides")
    if source_slide_position < 1 or source_slide_position > count:
        raise MoveSlideInvalidSourcePositionError(f"{source_slide_position} not in [1, {count}]")
    if destination_slide_position < 1 or destination_slide_position > count:
        raise MoveSlideInvalidDestinationPositionError(f"{destination_slide_position} not in [1, {count}]")
    _reorder_slide(prs, source_slide_position - 1, destination_slide_position - 1)


def attach_to_running_power_point(presentation_name: str) -> PowerPointInstanceHandle:
    raise NotImplementedError(
        "AttachToRunningPowerPoint targets a live COM process; python-pptx has no such concept"
    )


def copy_paste_power_point_slide(
    source: PowerPointInstanceHandle,
    source_slide_position: int,
    destination: PowerPointInstanceHandle,
    destination_slide_position: int,
) -> None:
    raise NotImplementedError(
        "CopyPastePowerPointSlide requires COM-level Slide.Copy()/Slides.Paste() fidelity "
        "(layouts, animations, embedded objects); an XML-level clone via python-pptx risks "
        "corrupting the package, so this is deliberately left unimplemented"
    )
