import shutil
import tarfile
import urllib.request
from pathlib import Path

import pytest

TEMPLATE_SHA = "1046d8fba6b42d367da6314c934cddb6bfe5662e"
TEMPLATE_URL = f"https://codeload.github.com/github/gitignore/tar.gz/{TEMPLATE_SHA}"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add CLI options to pytest."""
    parser.addoption(
        "--download-templates",
        action="store_true",
        default=False,
        help="Force download of gitignore templates even if they exist locally.",
    )
    parser.addoption(
        "--offline",
        action="store_true",
        default=False,
        help="Fail if templates are missing instead of downloading them.",
    )


@pytest.fixture(scope="session")
def templates_dir(pytestconfig: pytest.Config) -> Path:
    """Fixture to provide a local directory of gitignore templates."""
    fixture_dir = pytestconfig.rootpath / ".test_fixtures" / "gitignore"
    force_download = pytestconfig.getoption("--download-templates")
    offline = pytestconfig.getoption("--offline")

    if force_download or not fixture_dir.exists():
        if offline:
            pytest.fail(f"Templates missing in {fixture_dir} and --offline is set.")

        fixture_dir.mkdir(parents=True, exist_ok=True)
        tar_path = fixture_dir.parent / "templates.tar.gz"

        # Download the tarball
        with (
            urllib.request.urlopen(TEMPLATE_URL) as response,
            tar_path.open("wb") as f,
        ):
            f.write(response.read())

        # Extract it
        with tarfile.open(tar_path, mode="r:gz") as tar:
            tar.extractall(path=fixture_dir.parent)  # noqa: S202

        # The extraction creates a directory like 'gitignore-SHA'
        # We move its contents to our target directory
        extracted_dir = fixture_dir.parent / f"gitignore-{TEMPLATE_SHA}"
        for item in extracted_dir.iterdir():
            shutil.move(str(item), str(fixture_dir / item.name))

        extracted_dir.rmdir()
        tar_path.unlink()

    return fixture_dir
