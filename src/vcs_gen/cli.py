#!/usr/bin/env python3
# Usage (ephemeral):
#   SCRIPT_URL="https://gist.github.com/mkobit/gitignore-gen/raw/vcs_gen.py"
#   curl -sSfL $SCRIPT_URL | python3 - gitignore generate Python
#
# Development commands:
#   uv run ruff check .
#   uv run ty check src/
#   uv run pytest tests/
#
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Toolkit to compose configuration files for Git, JJ, and other VCS.

Source:  https://github.com/github/gitignore
Mirrors: https://codeload.github.com (default)

Example usage:
  # Search for gitignore templates
  vcs-gen gitignore search Python

  # Generate a gitignore file
  vcs-gen gitignore generate Python macOS --output .gitignore

  # Advanced pipeline with local sources
  vcs-gen gitignore generate \\
    --repo github/gitignore Python macOS \\
    --local-dir ./templates Python
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import io
import logging
import os
import re
import sys
import tarfile
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_REPO = "github/gitignore"

logger = logging.getLogger("vcs-gen")


def _get_default_cache() -> Path:
    """Return the XDG cache directory or a fallback."""
    try:
        home = Path.home()
    except (RuntimeError, ImportError):
        home = Path(os.environ.get("TMPDIR", "/tmp"))  # noqa: S108

    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "vcs-gen"
    return home / ".cache" / "vcs-gen"


def _parse_duration(duration_str: str) -> datetime.timedelta:
    """Parse a simple duration string into a timedelta."""
    match = re.match(r"(\d+)([dhm])", duration_str.lower())
    if not match:
        try:
            return datetime.timedelta(days=int(duration_str))
        except ValueError as e:
            msg = f"Invalid duration format: {duration_str}. Use e.g., '7d', '12h'."
            raise ValueError(msg) from e

    value, unit = int(match.group(1)), match.group(2)
    return {
        "d": datetime.timedelta(days=value),
        "h": datetime.timedelta(hours=value),
        "m": datetime.timedelta(minutes=value),
    }[unit]


def _setup_logging(verbosity: int) -> None:
    """Configure standard Python logging to stderr."""
    level = {0: logging.ERROR, 1: logging.INFO, 2: logging.DEBUG}.get(
        verbosity, logging.DEBUG
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )


class Color:
    """ANSI color codes for terminal output."""

    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def enabled(cls) -> bool:
        """Check if colors should be enabled."""
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def wrap(cls, text: str, color: str) -> str:
        """Wrap text in ANSI color codes if enabled."""
        if cls.enabled():
            return f"{color}{text}{cls.RESET}"
        return text


class TemplateMember(ABC):
    """Abstract interface for a single template file in a source."""

    def __init__(self, path: str, source_label: str, ref_label: str):
        self.path = path
        self.source_label = source_label
        self.ref_label = ref_label
        self.content: str | None = None

    @abstractmethod
    async def load(self) -> None:
        """Load the content of the template."""


class TarTemplateMember(TemplateMember):
    """Template member stored within a tar archive."""

    def __init__(
        self,
        path: str,
        source_label: str,
        ref_label: str,
        tar: tarfile.TarFile,
        internal_name: str,
    ):
        super().__init__(path, source_label, ref_label)
        self._tar = tar
        self._internal_name = internal_name

    async def load(self) -> None:
        self.content = await asyncio.to_thread(self._sync_read)

    def _sync_read(self) -> str | None:
        try:
            extracted = self._tar.extractfile(self._internal_name)
            if extracted:
                return extracted.read().decode("utf-8").strip()
        except Exception:
            logger.exception("Failed to read tar member: %s", self._internal_name)
        return None


class FileTemplateMember(TemplateMember):
    """Template member stored as a local file."""

    def __init__(self, path: str, source_label: str, ref_label: str, full_path: Path):
        super().__init__(path, source_label, ref_label)
        self._full_path = full_path

    async def load(self) -> None:
        self.content = await asyncio.to_thread(self._sync_read)

    def _sync_read(self) -> str | None:
        try:
            return self._full_path.read_text(encoding="utf-8").strip()
        except Exception:
            logger.exception("Failed to read local file: %s", self._full_path)
        return None


class LiteralTemplateMember(TemplateMember):
    """Template member with literal content."""

    def __init__(self, path: str, source_label: str, content: str):
        super().__init__(path, source_label, "literal")
        self.content = content

    async def load(self) -> None:
        pass


class TemplateSource(ABC):
    """Abstract interface for a source of templates."""

    @abstractmethod
    async def get_members(self) -> list[TemplateMember]:
        """Return all available templates in this source."""

    @property
    @abstractmethod
    def source_label(self) -> str:
        """Label for metadata headers."""

    @property
    @abstractmethod
    def ref_label(self) -> str:
        """Reference for metadata headers."""

    async def close(self) -> None:  # noqa: B027
        """Release resources associated with this source."""


class GitHubArchiveSource(TemplateSource):
    """Source that downloads a GitHub repository tarball."""

    def __init__(self, repo: str, ref: str, args: argparse.Namespace):
        self.repo = repo
        self.ref = ref
        self.args = args
        self._tar: tarfile.TarFile | None = None
        self.archive_path: Path | None = None

    @property
    def source_label(self) -> str:
        return self.repo

    @property
    def ref_label(self) -> str:
        return self.ref

    async def _get_data(self) -> bytes | None:
        return await asyncio.to_thread(self._sync_get_data)

    def _sync_get_data(self) -> bytes | None:
        base_url = getattr(self.args, "base_url", "https://codeload.github.com")
        if base_url is None:
            base_url = "https://codeload.github.com"

        slug = self.repo.replace("/", "_")
        cache_dir = cast("Path", self.args.download_location)
        self.archive_path = cache_dir / f"{slug}_{self.ref}.tar.gz"

        if self.archive_path.exists():
            try:
                now = datetime.datetime.now(tz=datetime.timezone.utc)
                mtime = datetime.datetime.fromtimestamp(
                    self.archive_path.stat().st_mtime, tz=datetime.timezone.utc
                )
                period = cast("str", self.args.refresh_period)
                if (now - mtime) < _parse_duration(period):
                    logger.info("Using cached archive from %s", self.archive_path)
                    return self.archive_path.read_bytes()
            except Exception:
                logger.warning("Failed to read cache file")

        url = f"{base_url.rstrip('/')}/{self.repo}/tar.gz/{self.ref}"
        logger.info("Downloading archive for %s @ %s", self.repo, self.ref)

        try:
            headers = {"User-Agent": "gitfiles-gen-script"}
            token = os.environ.get("GITHUB_TOKEN")
            no_auth = getattr(self.args, "no_auth", False)
            if not no_auth and token and "github.com" in url:
                headers["Authorization"] = f"token {token}"

            req = urllib.request.Request(url, headers=headers)  # noqa: S310
            with urllib.request.urlopen(req) as response:  # noqa: S310
                data = response.read()
                try:
                    self.archive_path.parent.mkdir(parents=True, exist_ok=True)
                    self.archive_path.write_bytes(data)
                except OSError as e:
                    logger.warning("Cache write failed (proceeding in memory): %s", e)
                return data
        except Exception:
            logger.exception("Failed to download archive from %s", url)
            return None

    async def get_members(self) -> list[TemplateMember]:
        data = await self._get_data()
        if not data:
            return []

        def open_tar() -> tarfile.TarFile:
            return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")

        self._tar = await asyncio.to_thread(open_tar)
        members: list[TemplateMember] = []
        for m in self._tar.getmembers():
            if m.isfile() and m.name.endswith(".gitignore"):
                parts = m.name.split("/")
                path = "/".join(parts[1:]) if len(parts) > 1 else m.name
                members.append(
                    TarTemplateMember(
                        path, self.source_label, self.ref_label, self._tar, m.name
                    )
                )
        return members

    async def close(self) -> None:
        if self._tar:
            await asyncio.to_thread(self._tar.close)
        if (
            getattr(self.args, "delete_archive", False) and self.archive_path
        ):  # pragma: no cover

            def unlink_file():
                if self.archive_path and self.archive_path.exists():
                    self.archive_path.unlink()

            await asyncio.to_thread(unlink_file)
            logger.info("Deleted archive %s", self.archive_path)


class LocalArchiveSource(TemplateSource):
    """Source that reads templates from a local .tar.gz archive."""

    def __init__(self, path: Path):
        self.path = path
        self._tar: tarfile.TarFile | None = None

    @property
    def source_label(self) -> str:
        return "local-archive"

    @property
    def ref_label(self) -> str:
        return self.path.as_posix()

    async def get_members(self) -> list[TemplateMember]:
        try:

            def open_tar() -> tarfile.TarFile:
                return tarfile.open(self.path, mode="r:gz")

            self._tar = await asyncio.to_thread(open_tar)
            return [
                TarTemplateMember(
                    m.name, self.source_label, self.ref_label, self._tar, m.name
                )
                for m in self._tar.getmembers()
                if m.isfile() and m.name.endswith(".gitignore")
            ]
        except Exception:
            logger.exception("Failed to open local archive: %s", self.path)
            return []

    async def close(self) -> None:
        if self._tar:
            await asyncio.to_thread(self._tar.close)


class LocalDirSource(TemplateSource):
    """Source that reads templates from a local directory."""

    def __init__(self, path: Path):
        self.path = path

    @property
    def source_label(self) -> str:
        return "local-dir"

    @property
    def ref_label(self) -> str:
        return self.path.as_posix()

    async def get_members(self) -> list[TemplateMember]:
        return await asyncio.to_thread(self._sync_get_members)

    def _sync_get_members(self) -> list[TemplateMember]:
        members: list[TemplateMember] = []
        for p in self.path.rglob("*.gitignore"):
            if p.is_file():
                # Use .as_posix() to ensure canonical '/' delimiters on Windows
                rel_path = p.relative_to(self.path).as_posix()
                members.append(
                    FileTemplateMember(rel_path, self.source_label, self.ref_label, p)
                )
        return members


class SelectionRequest:
    """Represents a single template selection request."""

    def __init__(self, type_: str, pattern: str):
        self.type = type_.replace("include_", "")
        self.pattern = pattern

    def matches(self, m: TemplateMember) -> bool:
        """Check if a template member matches this request."""
        n = m.path.rsplit("/", 1)[-1]

        def name_match(target: str, query: str, case_sensitive: bool = True) -> bool:
            if not case_sensitive:
                target, query = target.lower(), query.lower()
            if query.endswith(".gitignore"):
                return target == query
            return target in (f"{query}.gitignore", query)

        if self.type == "path":
            return m.path.endswith(self.pattern)
        if self.type == "file":
            return name_match(n, self.pattern)
        if self.type == "file_i":
            return name_match(n, self.pattern, case_sensitive=False)
        if self.type in {"filename", "templates"}:
            if "/" in self.pattern:
                return name_match(m.path, self.pattern)
            return name_match(n, self.pattern)
        return bool(self.type == "regex" and re.search(self.pattern, m.path))


class PipelineEvent:
    """Represents an event in the CLI pipeline."""

    def __init__(self, dest: str, value: Any, option_string: str | None = None):
        self.dest = dest
        self.value = value
        self.option_string = option_string


class PipelineAction(argparse.Action):
    """Custom argparse action to store events in order."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        _ = parser
        pipeline = getattr(namespace, "pipeline", None)
        if pipeline is None:
            pipeline = []
            namespace.pipeline = pipeline

        pipeline_list = cast("list[PipelineEvent]", pipeline)
        if values is None:
            return
        if isinstance(values, (list, tuple)):
            for val in values:
                pipeline_list.append(PipelineEvent(self.dest, val, option_string))
        else:
            pipeline_list.append(PipelineEvent(self.dest, values, option_string))


def _add_selection_group(parser: argparse.ArgumentParser) -> None:
    """Add template selection arguments to a parser."""
    selection = parser.add_argument_group("Selection options")
    selection.add_argument("--include-path", action=PipelineAction, metavar="PATH")
    selection.add_argument("--include-file", action=PipelineAction, metavar="FILENAME")
    selection.add_argument(
        "--include-file-i", action=PipelineAction, metavar="FILENAME"
    )
    selection.add_argument("--include-filename", action=PipelineAction, metavar="NAME")
    selection.add_argument("--include-regex", action=PipelineAction, metavar="PATTERN")
    selection.add_argument("--include-text", action=PipelineAction, metavar="TEXT")
    selection.add_argument(
        "--include-local-file", action=PipelineAction, metavar="PATH", type=Path
    )
    selection.add_argument("--fail-on-missing", action="store_true", default=True)
    selection.add_argument(
        "--no-fail-on-missing", action="store_false", dest="fail_on_missing"
    )


def _add_domain_subparser(
    subparsers: argparse._SubParsersAction,
    domain: str,
    help_text: str,
    common: argparse.ArgumentParser,
) -> None:
    """Add a domain subparser (e.g., gitignore, gitattributes)."""
    parser = subparsers.add_parser(domain, help=help_text)
    gi_sub = parser.add_subparsers(dest="command", required=True, title="Commands")

    ls_parser = gi_sub.add_parser("ls", help="List templates.", parents=[common])
    ls_parser.add_argument(
        "templates", nargs="*", action=PipelineAction, metavar="TEMPLATE"
    )
    _add_selection_group(ls_parser)

    search_parser = gi_sub.add_parser(
        "search", help="Search templates.", parents=[common]
    )
    search_parser.add_argument(
        "include_regex", nargs="?", action=PipelineAction, metavar="PATTERN"
    )
    _add_selection_group(search_parser)

    gen_parser = gi_sub.add_parser(
        "generate", help=f"Generate .{domain}.", parents=[common], aliases=["gen"]
    )
    gen_parser.add_argument(
        "templates", nargs="*", action=PipelineAction, metavar="TEMPLATE"
    )
    _add_selection_group(gen_parser)

    output = gen_parser.add_argument_group("Output options")
    output.add_argument("--output", metavar="FILE")
    output.add_argument(
        "--section-order", choices=["lexicographic", "args_order"], default="args_order"
    )
    output.add_argument(
        "--dry-run", action="store_true", help="Show selected templates."
    )
    output.add_argument("--include-file-header", action="store_true", default=True)
    output.add_argument(
        "--no-include-file-header", action="store_false", dest="include_file_header"
    )
    output.add_argument("--file-header-template", metavar="STR")
    output.add_argument("--include-section-header", action="store_true", default=True)
    output.add_argument(
        "--no-include-section-header",
        action="store_false",
        dest="include_section_header",
    )
    output.add_argument("--section-header-template", metavar="STR")


def _create_parser() -> argparse.ArgumentParser:
    """Define the command line interface with subcommands."""
    parser = argparse.ArgumentParser(
        description="Toolkit to compose configuration files for Git and other VCS."
    )
    subparsers = parser.add_subparsers(dest="domain", required=True, title="Domains")

    common = argparse.ArgumentParser(add_help=False)

    source = common.add_argument_group("Repository source")
    source.add_argument("--repo", action=PipelineAction, default=_DEFAULT_REPO)
    source.add_argument("--no-auth", action="store_true")
    source.add_argument("--base-url", action=PipelineAction, metavar="URL")
    source.add_argument("--branch", action=PipelineAction, default="main")
    source.add_argument("--tag", action=PipelineAction, metavar="TAG")
    source.add_argument("--sha", action=PipelineAction, metavar="HASH")

    local = common.add_argument_group("Local sources")
    local.add_argument("--local-dir", action=PipelineAction, type=Path, metavar="PATH")
    local.add_argument(
        "--local-archive", action=PipelineAction, type=Path, metavar="PATH"
    )

    storage = common.add_argument_group("Storage and logging")
    storage.add_argument(
        "--download-location", type=Path, default=_get_default_cache(), metavar="DIR"
    )
    storage.add_argument("--log-level", type=int, choices=[0, 1, 2], default=1)
    storage.add_argument("--refresh-period", metavar="DURATION", default="7d")
    storage.add_argument(
        "--delete-archive", action="store_true", help="Delete archive after run."
    )

    _add_domain_subparser(subparsers, "gitignore", "Manage .gitignore files.", common)
    _add_domain_subparser(
        subparsers, "gitattributes", "Manage .gitattributes files.", common
    )

    return parser


async def _handle_inclusion(
    d: str,
    v: Any,
    src: TemplateSource,
    all_m: list[TemplateMember],
    args: argparse.Namespace,
) -> list[TemplateMember]:
    """Execute a single inclusion request."""
    incl = {
        "templates",
        "include_path",
        "include_file",
        "include_file_i",
        "include_filename",
        "include_regex",
    }
    if d in incl:
        req = SelectionRequest(d, cast("str", v))
        matches = [m for m in all_m if req.matches(m)]
        if not matches and getattr(args, "fail_on_missing", True):
            err = f"No match for {d}={v} in {src.source_label}"
            raise ValueError(err)
        if not getattr(args, "dry_run", False):
            for m in matches:
                await m.load()
        return matches
    if d == "include_text":
        return [LiteralTemplateMember("literal", "text", cast("str", v))]
    if d == "include_local_file":
        p = cast("Path", v)
        txt = (
            f"# Content of {p}"
            if getattr(args, "dry_run", False)
            else await asyncio.to_thread(p.read_text, encoding="utf-8")
        )
        return [LiteralTemplateMember(str(p), "local-file", txt.strip())]
    return []


async def _run_pipeline(args: argparse.Namespace) -> list[TemplateMember]:
    """Execute the pipeline of events to collect templates."""
    pipeline = cast("list[PipelineEvent]", getattr(args, "pipeline", []))
    st = {
        "repo": _DEFAULT_REPO,
        "ref": "main",
        "base_url": "https://codeload.github.com",
        "local_dir": None,
        "local_archive": None,
    }
    cur_src: TemplateSource | None = None
    all_m: list[TemplateMember] = []
    col: list[TemplateMember] = []

    async def get_src() -> TemplateSource:
        nonlocal cur_src, all_m
        if cur_src:
            return cur_src
        if st["local_dir"]:
            s = LocalDirSource(cast("Path", st["local_dir"]))
        elif st["local_archive"]:
            s = LocalArchiveSource(cast("Path", st["local_archive"]))
        else:
            s = GitHubArchiveSource(
                cast("str", st["repo"]), cast("str", st["ref"]), args
            )
        cur_src, all_m = s, await s.get_members()
        return s

    try:
        for ev in pipeline:
            d, v = ev.dest, ev.value
            if d in {
                "repo",
                "branch",
                "tag",
                "sha",
                "base_url",
                "local_dir",
                "local_archive",
            }:
                st["ref" if d in {"branch", "tag", "sha"} else d], cur_src = v, None
            else:
                src = await get_src()
                col.extend(await _handle_inclusion(d, v, src, all_m, args))
        if args.command == "search" or (args.command == "ls" and not col):
            src = await get_src()
            col = all_m
        return col
    finally:
        if cur_src:
            await cur_src.close()


def _get_headers(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve formatting templates for the final output."""
    f_tmpl = getattr(args, "file_header_template", None) or (
        "\n# Generated by vcs-gen\n# Date: {date}\n\n"
    )
    s_tmpl = getattr(args, "section_header_template", None) or (
        "### BEGIN {path} (Source: {source}@{ref}) ###\n{content}\n"
        "### END {path} ###\n\n"
    )
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    f_header = (
        f_tmpl.format(date=now) if getattr(args, "include_file_header", True) else ""
    )
    return f_header, s_tmpl


async def _do_generate(args: argparse.Namespace, col: list[TemplateMember]) -> None:
    """Handle formatting and output for the generate command."""
    if getattr(args, "dry_run", False):
        sys.stdout.write(
            Color.wrap(f"\n📦 Dry run: {len(col)} templates selected\n", Color.BOLD)
        )
        for m in col:
            sys.stdout.write(
                f"  {Color.wrap('+', Color.GREEN)} {m.path} "
                f"({Color.wrap(m.source_label, Color.CYAN)}@{m.ref_label})\n"
            )
        return

    if args.domain in {"gitignore", "gitattributes"}:
        if args.section_order == "lexicographic":
            col.sort(key=lambda x: x.path)
        f_header, s_tmpl = _get_headers(args)
        sections: list[str] = []
        for m in col:
            if m.content:
                if getattr(args, "include_section_header", True):
                    sections.append(
                        s_tmpl.format(
                            path=m.path,
                            source=m.source_label,
                            ref=m.ref_label,
                            content=m.content,
                        )
                    )
                else:
                    sections.append(f"{m.content}\n\n")
        final_output = f_header + "".join(sections)
        if args.output:

            def write_file():
                Path(args.output).write_text(final_output, encoding="utf-8")

            await asyncio.to_thread(write_file)
            logger.info("Successfully wrote output to %s", args.output)
        else:
            sys.stdout.write(final_output)


async def async_main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    parser = _create_parser()
    args = parser.parse_args(argv)
    _setup_logging(cast("int", getattr(args, "log_level", 1)))

    try:

        async def run_pipeline_and_output():
            col = await _run_pipeline(args)
            if args.command == "ls":
                for m in sorted(col, key=lambda x: x.path):
                    sys.stdout.write(
                        f"{m.path} (Source: {m.source_label}@{m.ref_label})\n"
                    )
                return
            if args.command == "search":
                pattern = ".*"
                pipeline = cast("list[PipelineEvent]", getattr(args, "pipeline", []))
                for ev in pipeline:
                    if ev.dest == "include_regex":
                        pattern = cast("str", ev.value)
                        break
                matched = [m for m in col if re.search(pattern, m.path, re.IGNORECASE)]
                sys.stdout.write(
                    f"\n🔍 Found {len(matched)} templates matching "
                    f"'{Color.wrap(pattern, Color.YELLOW)}':\n\n"
                )
                for m in sorted(matched, key=lambda x: x.path):
                    sys.stdout.write(f"  {Color.wrap('📄', Color.CYAN)} {m.path}\n")
                return
            if not col:
                if not getattr(args, "pipeline", None):
                    # Safely find the gitignore subparser to print its help
                    choices = next(
                        (
                            a.choices
                            for a in parser._actions  # noqa: SLF001
                            if isinstance(a, argparse._SubParsersAction)  # noqa: SLF001
                        ),
                        {},
                    )
                    gi_parser = choices.get("gitignore")
                    if gi_parser:
                        gi_parser.print_help()
                else:
                    logger.warning("No templates were collected.")
                return
            await _do_generate(args, col)

        await asyncio.wait_for(run_pipeline_and_output(), timeout=300)
    except Exception:
        logger.exception("Runtime error")
        sys.exit(1)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
