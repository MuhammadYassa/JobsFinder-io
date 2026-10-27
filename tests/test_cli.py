import subprocess
import sys

import pytest

from jobsfinder_io.cli import main


def test_cli_registry_workflow(database, capsys):
    path, _ = database
    db = ["--db", str(path)]
    assert (
        main(
            [
                *db,
                "add-employer",
                "--name",
                "Example",
                "--official-domain",
                "example.com",
            ]
        )
        == 0
    )
    assert "Employer 1" in capsys.readouterr().out
    source_args = [
        *db,
        "add-source",
        "--employer-id",
        "1",
        "--provider",
        "greenhouse",
        "--board-identifier",
        "example",
        "--careers-url",
        "https://example.com/careers",
    ]
    assert main(source_args) == 0
    assert "candidate" in capsys.readouterr().out
    assert main(source_args) == 1
    assert "already registered" in capsys.readouterr().err
    assert main([*db, "validate-source", "1"]) == 1
    assert "Confirm" in capsys.readouterr().err
    assert (
        main(
            [
                *db,
                "validate-source",
                "1",
                "--confirm-official-association",
                "--confirm-public-access",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main([*db, "list-sources"]) == 0
    assert "validated" in capsys.readouterr().out
    assert main([*db, "list-postings"]) == 0
    assert capsys.readouterr().out == ""
    # Separate interpreter proves command operation does not depend on process state.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from jobsfinder_io.cli import main; raise SystemExit(main())",
            *db,
            "list-sources",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "example" in result.stdout


def test_missing_and_unmigrated_database(tmp_path, capsys):
    path = tmp_path / "empty.db"
    assert main(["--db", str(path), "list-sources"]) == 1
    assert not path.exists()
    assert "Alembic" in capsys.readouterr().err
    path.touch()
    assert main(["--db", str(path), "list-sources"]) == 1
    assert "Database operation failed" in capsys.readouterr().err


def test_argparse_input_error():
    with pytest.raises(SystemExit) as exc:
        main(["add-source", "--employer-id", "not-a-number"])
    assert exc.value.code == 2
