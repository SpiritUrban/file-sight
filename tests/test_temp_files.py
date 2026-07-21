from pathlib import Path

from filesight.temp_files import FrameWorkspace


def test_video_dir_created_and_isolated(tmp_path: Path) -> None:
    with FrameWorkspace(base=tmp_path / "root") as ws:
        d1 = ws.video_dir()
        d2 = ws.video_dir()
        assert d1.exists() and d2.exists()
        assert d1 != d2
        assert d1.parent == ws.operation_dir


def test_cleanup_video_removes_only_that_dir(tmp_path: Path) -> None:
    with FrameWorkspace(base=tmp_path / "root") as ws:
        d1 = ws.video_dir()
        d2 = ws.video_dir()
        (d1 / "frame.jpg").write_bytes(b"x")
        ws.cleanup_video(d1)
        assert not d1.exists()
        assert d2.exists()


def test_cleanup_removes_whole_tree(tmp_path: Path) -> None:
    ws = FrameWorkspace(base=tmp_path / "root")
    d = ws.video_dir()
    assert ws.operation_dir.exists()
    ws.cleanup()
    assert not ws.operation_dir.exists()
    assert not d.exists()


def test_context_manager_cleans_up_on_exit(tmp_path: Path) -> None:
    with FrameWorkspace(base=tmp_path / "root") as ws:
        ws.video_dir()
        op_dir = ws.operation_dir
        assert op_dir.exists()
    assert not op_dir.exists()


def test_cleanup_video_refuses_foreign_path(tmp_path: Path) -> None:
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    (outsider / "keep.txt").write_bytes(b"important")
    with FrameWorkspace(base=tmp_path / "root") as ws:
        ws.video_dir()  # realize the workspace
        ws.cleanup_video(outsider)  # not under operation_dir -> ignored
    assert (outsider / "keep.txt").exists()
