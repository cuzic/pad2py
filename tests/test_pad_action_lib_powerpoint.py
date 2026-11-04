"""`pad_action_lib.powerpoint_actions`の単体テスト(`python-pptx`で実際の.pptxファイルを操作)。"""
from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from dump_daemon.pad_action_lib import powerpoint_actions as pp


def test_launch_new_presentation_starts_empty() -> None:
    instance = pp.launch_power_point()
    assert len(instance.presentation.slides) == 0
    assert instance.path is None


def test_launch_stored_presentation_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(pp.LaunchPowerPointFileNotFoundError):
        pp.launch_power_point(mode="StoredPresentation", path=str(tmp_path / "missing.pptx"))


def test_launch_stored_presentation_invalid_extension_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.ppt"
    f.write_bytes(b"not a real file")
    with pytest.raises(pp.LaunchPowerPointInvalidFileTypeError):
        pp.launch_power_point(mode="StoredPresentation", path=str(f))


def test_add_write_save_reload_round_trip(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    index = pp.add_power_point_slide(instance)
    assert index == 1
    pp.write_to_power_point(instance, "hello world", write_mode="FirstSlide")

    dest = tmp_path / "out.pptx"
    pp.save_power_point(instance, save_mode="SaveAs", document_path=str(dest))
    assert dest.exists()

    reloaded = Presentation(str(dest))
    assert len(reloaded.slides) == 1
    shapes_text = [s.text_frame.text for s in reloaded.slides[0].shapes if s.has_text_frame]
    assert "hello world" in shapes_text


def test_write_to_power_point_appends_without_separator_by_default() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    pp.write_to_power_point(instance, "foo")
    pp.write_to_power_point(instance, "bar")  # AppendNewLineの既定はfalse
    text = pp.read_from_power_point(instance)
    assert "foobar" in text


def test_write_to_power_point_appends_with_newline_when_requested() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    pp.write_to_power_point(instance, "foo")
    pp.write_to_power_point(instance, "bar", append_new_line=True)
    text = pp.read_from_power_point(instance)
    assert "foo\nbar" in text


def test_write_to_power_point_no_slides_raises() -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.WritePowerPointNoSlidesError):
        pp.write_to_power_point(instance, "x")


def test_write_to_power_point_invalid_position_raises() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    with pytest.raises(pp.WritePowerPointInvalidSlidePositionError):
        pp.write_to_power_point(instance, "x", write_mode="AtPosition", slide_position=5)


def test_read_from_power_point_whole_presentation() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    pp.add_power_point_slide(instance)
    pp.write_to_power_point(instance, "slide one", write_mode="FirstSlide")
    pp.write_to_power_point(instance, "slide two", write_mode="LastSlide")
    text = pp.read_from_power_point(instance)
    assert "slide one" in text
    assert "slide two" in text


def test_read_from_power_point_slide_range() -> None:
    instance = pp.launch_power_point()
    for i in range(1, 4):
        pp.add_power_point_slide(instance)
        pp.write_to_power_point(instance, f"slide {i}", write_mode="AtPosition", slide_position=i)

    text = pp.read_from_power_point(instance, read_mode="Slides", slides="1,3")
    assert "slide 1" in text
    assert "slide 2" not in text
    assert "slide 3" in text


def test_read_from_power_point_range_end_clamps_silently() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    pp.write_to_power_point(instance, "only slide")
    text = pp.read_from_power_point(instance, read_mode="Slides", slides="1-99")
    assert "only slide" in text  # 範囲の終了側はスライド数に黙ってクランプされる、エラーにならない


def test_read_from_power_point_single_number_beyond_count_is_silently_skipped() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    pp.write_to_power_point(instance, "only slide")
    text = pp.read_from_power_point(instance, read_mode="Slides", slides="1,99")
    assert text.strip() == "only slide"  # エラーにならず、単に99番は出力されない


def test_read_from_power_point_invalid_range_syntax_raises() -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.ReadPowerPointError):
        pp.read_from_power_point(instance, read_mode="Slides", slides="not-a-range")


def test_add_power_point_slide_at_position_inserts_and_reindexes() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)  # slide 1
    pp.write_to_power_point(instance, "first")
    pp.add_power_point_slide(instance)  # slide 2 (LastSlide既定)
    pp.write_to_power_point(instance, "second", write_mode="LastSlide")
    pp.add_power_point_slide(instance, add_slide_position="AtPosition", slide_position=2)
    pp.write_to_power_point(instance, "inserted", write_mode="AtPosition", slide_position=2)

    assert len(instance.presentation.slides) == 3
    text = pp.read_from_power_point(instance, read_mode="Slides", slides="1")
    assert "first" in text
    text2 = pp.read_from_power_point(instance, read_mode="Slides", slides="2")
    assert "inserted" in text2
    text3 = pp.read_from_power_point(instance, read_mode="Slides", slides="3")
    assert "second" in text3


def test_add_power_point_slide_invalid_position_raises() -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.AddPowerPointSlideInvalidPositionError):
        pp.add_power_point_slide(instance, add_slide_position="AtPosition", slide_position=5)


def test_delete_power_point_slide_no_slides_raises() -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.DeletePowerPointSlideNoSlidesError):
        pp.delete_power_point_slide(instance)


def test_delete_power_point_slide_removes_target() -> None:
    instance = pp.launch_power_point()
    for i in range(1, 4):
        pp.add_power_point_slide(instance)
        pp.write_to_power_point(instance, f"slide {i}", write_mode="AtPosition", slide_position=i)

    pp.delete_power_point_slide(instance, delete_slide_position="AtPosition", slide_position=2)
    assert len(instance.presentation.slides) == 2
    text = pp.read_from_power_point(instance)
    assert "slide 1" in text
    assert "slide 2" not in text
    assert "slide 3" in text


def test_delete_power_point_slide_invalid_position_raises() -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    with pytest.raises(pp.DeletePowerPointSlideInvalidPositionError):
        pp.delete_power_point_slide(instance, delete_slide_position="AtPosition", slide_position=5)


def test_move_power_point_slide_same_presentation() -> None:
    instance = pp.launch_power_point()
    for i in range(1, 4):
        pp.add_power_point_slide(instance)
        pp.write_to_power_point(instance, f"slide {i}", write_mode="AtPosition", slide_position=i)

    pp.move_power_point_slide(instance, 3, instance, 1)
    text1 = pp.read_from_power_point(instance, read_mode="Slides", slides="1")
    assert "slide 3" in text1
    text3 = pp.read_from_power_point(instance, read_mode="Slides", slides="3")
    assert "slide 2" in text3


def test_move_power_point_slide_cross_presentation_not_implemented() -> None:
    source = pp.launch_power_point()
    pp.add_power_point_slide(source)
    destination = pp.launch_power_point()
    pp.add_power_point_slide(destination)
    with pytest.raises(NotImplementedError):
        pp.move_power_point_slide(source, 1, destination, 1)


def test_move_power_point_slide_source_no_slides_raises() -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.MoveSlideSourceNoSlidesError):
        pp.move_power_point_slide(instance, 1, instance, 1)


def test_save_as_unsupported_extension_raises(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.SavePowerPointUnsupportedExtensionError):
        pp.save_power_point(instance, save_mode="SaveAs", document_path=str(tmp_path / "out.txt"))


def test_save_as_format_mismatch_raises(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.SavePowerPointFormatMismatchError):
        pp.save_power_point(
            instance, save_mode="SaveAs", document_format="PPTX", document_path=str(tmp_path / "out.ppt")
        )


def test_save_as_validated_but_unwritable_format_raises_not_implemented(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    with pytest.raises(NotImplementedError):
        pp.save_power_point(instance, save_mode="SaveAs", document_path=str(tmp_path / "out.pdf"))


def test_save_instance_none_raises() -> None:
    with pytest.raises(pp.SavePowerPointInstanceNullError):
        pp.save_power_point(None)


def test_close_do_not_save_is_a_noop() -> None:
    instance = pp.launch_power_point()
    pp.close_power_point(instance)  # 例外を投げないことを確認するだけ


def test_close_save_without_path_raises(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    with pytest.raises(pp.SavePowerPointError):
        pp.close_power_point(instance, close_mode="Save")


def test_close_save_as_writes_file(tmp_path: Path) -> None:
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    dest = tmp_path / "out.pptx"
    pp.close_power_point(instance, close_mode="SaveAs", document_path=str(dest))
    assert dest.exists()


def test_attach_and_copy_paste_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        pp.attach_to_running_power_point("whatever")
    instance = pp.launch_power_point()
    pp.add_power_point_slide(instance)
    with pytest.raises(NotImplementedError):
        pp.copy_paste_power_point_slide(instance, 1, instance, 1)
