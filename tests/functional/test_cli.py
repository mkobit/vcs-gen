from pathlib import Path
from unittest.mock import Mock

import pytest

from vcs_gen.cli import _handle_inclusion, async_main


@pytest.mark.asyncio
async def test_cli_ls(templates_dir: Path):
    """Test the 'ls' subcommand using a local directory."""
    await async_main(["gitignore", "ls", "--local-dir", str(templates_dir), "Python"])


@pytest.mark.asyncio
async def test_cli_search(templates_dir: Path, capsys: pytest.CaptureFixture[str]):
    """Test the 'search' subcommand."""
    # Search for Python in fixtures
    await async_main(
        [
            "gitignore",
            "search",
            "--local-dir",
            str(templates_dir),
            "--include-regex",
            "Python",
        ]
    )
    captured = capsys.readouterr()
    assert "🔍 Found" in captured.out
    assert "Python.gitignore" in captured.out


@pytest.mark.asyncio
async def test_cli_dry_run(templates_dir: Path, capsys: pytest.CaptureFixture[str]):
    """Test 'generate' with --dry-run."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "Python",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert "📦 Dry run" in captured.out
    assert "+" in captured.out
    assert "Python.gitignore" in captured.out


@pytest.mark.asyncio
async def test_cli_generate_to_stdout(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test generating a gitignore to stdout."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "Python",
            "--no-include-file-header",
        ]
    )
    captured = capsys.readouterr()
    assert "### BEGIN Python.gitignore" in captured.out
    assert "Source: local-dir" in captured.out
    assert "### END Python.gitignore ###" in captured.out


@pytest.mark.asyncio
async def test_cli_generate_to_file(templates_dir: Path, tmp_path: Path):
    """Test generating a gitignore to a file."""
    output_file = tmp_path / ".gitignore"
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "Python",
            "macOS",
            "--output",
            str(output_file),
        ]
    )

    assert output_file.exists()
    content = output_file.read_text()
    assert "### BEGIN Python.gitignore" in content
    assert "### BEGIN Global/macOS.gitignore" in content


@pytest.mark.asyncio
async def test_cli_include_text(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test including literal text."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "--include-text",
            "# Custom Header",
            "Python",
            "--no-include-file-header",
            "--no-include-section-header",
        ]
    )
    captured = capsys.readouterr()
    assert "# Custom Header" in captured.out
    assert "marimo" in captured.out  # Part of Python.gitignore in fixtures


@pytest.mark.asyncio
async def test_cli_include_local_file(
    templates_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Test including a local file."""
    custom_file = tmp_path / "custom.gitignore"
    custom_file.write_text("*.log", encoding="utf-8")

    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "--include-local-file",
            str(custom_file),
            "--no-include-file-header",
            "--no-include-section-header",
        ]
    )
    captured = capsys.readouterr()
    assert "*.log" in captured.out


@pytest.mark.asyncio
async def test_cli_fail_on_missing(templates_dir: Path):
    """Test failure when a template is missing."""
    with pytest.raises(SystemExit):
        await async_main(
            [
                "gitignore",
                "generate",
                "--local-dir",
                str(templates_dir),
                "NonExistentTemplate",
            ]
        )


@pytest.mark.asyncio
async def test_cli_no_fail_on_missing(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test --no-fail-on-missing."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "--no-fail-on-missing",
            "NonExistentTemplate",
            "Python",
            "--no-include-file-header",
        ]
    )
    captured = capsys.readouterr()
    assert "Python.gitignore" in captured.out


@pytest.mark.asyncio
async def test_cli_custom_header(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test custom file header template."""
    # Note: using generate first then arguments
    await async_main(
        [
            "gitignore",
            "generate",
            "Python",
            "--local-dir",
            str(templates_dir),
            "--file-header-template",
            "HEADER {date}",
            "--no-include-section-header",
        ]
    )
    captured = capsys.readouterr()
    assert "HEADER 2026-" in captured.out


@pytest.mark.asyncio
async def test_cli_no_templates_collected(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test when pipeline exists but no templates are collected."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "--no-fail-on-missing",
            "MissingTemplate",
        ]
    )


@pytest.mark.asyncio
async def test_cli_section_order_lexicographic(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test lexicographic section order."""
    await async_main(
        [
            "gitignore",
            "generate",
            "--local-dir",
            str(templates_dir),
            "macOS",
            "Python",
            "--section-order",
            "lexicographic",
            "--no-include-file-header",
            "--no-include-section-header",
        ]
    )
    captured = capsys.readouterr()
    assert captured.out != ""


@pytest.mark.asyncio
async def test_cli_search_positional(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test the 'search' subcommand with a positional argument."""
    # Search for Python in fixtures
    await async_main(
        [
            "gitignore",
            "search",
            "--local-dir",
            str(templates_dir),
            "Python",
        ]
    )
    captured = capsys.readouterr()
    assert "🔍 Found" in captured.out
    assert "Python.gitignore" in captured.out


@pytest.mark.asyncio
async def test_cli_gitattributes(
    templates_dir: Path, capsys: pytest.CaptureFixture[str]
):
    """Test the 'gitattributes' domain."""
    await async_main(
        [
            "gitattributes",
            "generate",
            "--local-dir",
            str(templates_dir),
            "Python",
            "--no-include-file-header",
        ]
    )
    captured = capsys.readouterr()
    assert "### BEGIN Python.gitignore" in captured.out


@pytest.mark.remote
@pytest.mark.asyncio
async def test_cli_delete_archive(tmp_path: Path):
    """Test the --delete-archive flag (requires network)."""
    # Use a custom download location to avoid polluting actual cache
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Run once without delete to ensure it exists
    await async_main(
        [
            "gitignore",
            "ls",
            "--repo",
            "github/gitignore",
            "--download-location",
            str(cache_dir),
            "Python",
        ]
    )

    # Check if archive exists
    archives = list(cache_dir.glob("*.tar.gz"))
    assert len(archives) == 1
    archive_path = archives[0]

    # Run again with delete
    await async_main(
        [
            "gitignore",
            "ls",
            "--repo",
            "github/gitignore",
            "--download-location",
            str(cache_dir),
            "--delete-archive",
            "Python",
        ]
    )

    assert not archive_path.exists()


@pytest.mark.asyncio
async def test_handle_inclusion_edge_case():
    """Test _handle_inclusion with an unknown destination."""
    res = await _handle_inclusion("unknown", "val", Mock(), [], Mock())
    assert res == []
