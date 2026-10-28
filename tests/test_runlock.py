import pytest

from jobsfinder_io.runlock import RunInProgress, database_run_lock


def test_lock_excludes_overlap_and_releases_on_exception(tmp_path):
    database = tmp_path / "registry.db"
    with pytest.raises(ValueError), database_run_lock(database):
        with pytest.raises(RunInProgress), database_run_lock(database):
            pytest.fail("overlap entered")
        raise ValueError("synthetic failure")
    with database_run_lock(database):
        pass
