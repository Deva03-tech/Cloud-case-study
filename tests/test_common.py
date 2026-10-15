import json
import os

import pytest

from src import common


# --- result writer -------------------------------------------------------------

def test_write_result_meta_and_data(tmp_path):
    path = common.write_result("unit_test", {"x": 1}, settings={"seed": 0}, results_dir=tmp_path)
    assert path == tmp_path / "unit_test.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["data"] == {"x": 1}
    meta = payload["meta"]
    assert meta["name"] == "unit_test"
    assert meta["settings"] == {"seed": 0}
    assert meta["git_commit"]
    assert meta["host"]["hostname"]
    assert meta["utc"].endswith("+00:00")
    assert meta["ist"].endswith("+05:30")
    assert not list(tmp_path.glob("*.tmp"))


def test_write_result_overwrites(tmp_path):
    common.write_result("r", {"v": 1}, results_dir=tmp_path)
    common.write_result("r", {"v": 2}, results_dir=tmp_path)
    assert json.loads((tmp_path / "r.json").read_text())["data"] == {"v": 2}


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "sp ace"])
def test_write_result_rejects_bad_names(tmp_path, bad):
    with pytest.raises(ValueError):
        common.write_result(bad, {}, results_dir=tmp_path)


# --- STATUS.md updater ------------------------------------------------------------

STATUS = """Next check-in: 01:00 IST

# STATUS

| # | Task | Status | Start | ETA | Finished |
| --- | --- | --- | --- | --- | --- |
| 1 | First | pending | | | |
| 2 | Second | pending | | | |

## Errors
"""


def test_update_task_and_checkin(tmp_path):
    p = tmp_path / "STATUS.md"
    p.write_text(STATUS, encoding="utf-8")
    common.update_task("2", status_path=p, status="done", start="00:10", finished="00:20")
    common.update_task("T3", status_path=p, task="Third", status="queued")
    common.set_next_checkin("02:00 IST", status_path=p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Next check-in: 02:00 IST"
    assert "| 1 | First | pending | | | |" in lines  # untouched rows keep their text
    assert "| 2 | Second | done | 00:10 |  | 00:20 |" in lines
    assert "| T3 | Third | queued |  |  |  |" in lines
    assert lines.index("| T3 | Third | queued |  |  |  |") < lines.index("## Errors")


def test_update_task_rejects_unknown_column(tmp_path):
    p = tmp_path / "STATUS.md"
    p.write_text(STATUS, encoding="utf-8")
    with pytest.raises(ValueError):
        common.update_task("1", status_path=p, colour="red")


# --- free-space guard ------------------------------------------------------------------

def test_free_space_guard_passes_and_trips(tmp_path):
    assert common.check_free_space(tmp_path, min_gb=0) > 0
    with pytest.raises(common.DiskSpaceError):
        common.check_free_space(tmp_path, min_gb=10**9)


# --- exclusive lock -----------------------------------------------------------------------

def test_lock_acquire_release(tmp_path):
    lock = tmp_path / "exclusive.lock"
    with common.exclusive_lock("a", lock_path=lock) as info:
        assert lock.exists()
        assert info["pid"] == os.getpid()
    assert not lock.exists()


def test_lock_busy_when_held(tmp_path):
    lock = tmp_path / "exclusive.lock"
    with common.exclusive_lock("a", lock_path=lock):
        with pytest.raises(common.LockBusy):
            with common.exclusive_lock("b", lock_path=lock):
                pass
    assert not lock.exists()


def test_lock_released_after_exception(tmp_path):
    lock = tmp_path / "exclusive.lock"
    with pytest.raises(RuntimeError):
        with common.exclusive_lock("a", lock_path=lock):
            raise RuntimeError("boom")
    assert not lock.exists()


def test_stale_lock_taken_over(tmp_path):
    lock = tmp_path / "exclusive.lock"
    lock.write_text(json.dumps({"task": "dead", "pid": 999999}), encoding="utf-8")
    with common.exclusive_lock("new", lock_path=lock) as info:
        assert json.loads(lock.read_text())["task"] == "new"
        assert info["task"] == "new"
    assert not lock.exists()


def test_corrupt_lock_treated_as_stale(tmp_path):
    lock = tmp_path / "exclusive.lock"
    lock.write_text("not json", encoding="utf-8")
    with common.exclusive_lock("new", lock_path=lock):
        pass


# --- keep-awake ----------------------------------------------------------------------------

def test_keep_awake_toggles():
    if os.name != "nt":
        pytest.skip("Windows only")
    with common.awake():
        pass
    assert common.keep_awake(False)
