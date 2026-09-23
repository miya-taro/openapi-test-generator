"""Assemble an isolated CPython runtime from the current Windows Python install."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Iterable

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


class RuntimePackageError(Exception):
    """Raised when the build Python cannot provide a valid portable runtime."""


def load_runtime_requirements(path: Path) -> list[Requirement]:
    requirements = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        spec = line.partition("#")[0].strip()
        if not spec:
            continue
        if spec.startswith(("-", ".", "/")):
            raise RuntimePackageError(f"{path}:{line_number}: file and option references are not supported")
        try:
            requirements.append(Requirement(spec))
        except Exception as exc:
            raise RuntimePackageError(f"{path}:{line_number}: invalid requirement: {spec}") from exc
    return requirements


def _active(requirement: Requirement, marker_environment: dict[str, str]) -> bool:
    if requirement.marker is None:
        return True
    return requirement.marker.evaluate({**marker_environment, "extra": ""})


def resolve_distribution_closure(
    requirements: Iterable[Requirement],
    distributions: Iterable[metadata.Distribution],
    marker_environment: dict[str, str] | None = None,
) -> list[metadata.Distribution]:
    available = {}
    for dist in distributions:
        name = dist.metadata.get("Name")
        if name:
            available.setdefault(canonicalize_name(name), dist)

    environment = marker_environment or default_environment()
    pending = list(requirements)
    resolved: dict[str, metadata.Distribution] = {}
    while pending:
        requirement = pending.pop(0)
        if not _active(requirement, environment):
            continue

        name = canonicalize_name(requirement.name)
        dist = available.get(name)
        if dist is None:
            raise RuntimePackageError(f"Runtime dependency is not installed: {requirement}")
        if requirement.specifier and dist.version not in requirement.specifier:
            raise RuntimePackageError(
                f"Installed {name} {dist.version} does not satisfy {requirement.specifier}"
            )
        if name in resolved:
            continue

        resolved[name] = dist
        for raw_requirement in dist.requires or []:
            try:
                dependency = Requirement(raw_requirement)
            except Exception as exc:
                raise RuntimePackageError(f"Invalid metadata requirement for {name}: {raw_requirement}") from exc
            if _active(dependency, environment):
                pending.append(dependency)

    return [resolved[name] for name in sorted(resolved)]


def _copy_python_files(python_home: Path, output: Path) -> str:
    executable = python_home / "python.exe"
    lib = python_home / "Lib"
    dlls = python_home / "DLLs"
    if not executable.is_file() or not lib.is_dir() or not dlls.is_dir():
        raise RuntimePackageError(f"Not a complete Windows CPython installation: {python_home}")

    versioned_dlls = sorted(python_home.glob("python[0-9][0-9][0-9].dll"))
    if not versioned_dlls:
        raise RuntimePackageError(f"Versioned CPython DLL was not found in {python_home}")
    dll_match = re.fullmatch(r"python([0-9]+)\.dll", versioned_dlls[-1].name)
    if dll_match is None:
        raise RuntimePackageError(f"Could not determine CPython version from {versioned_dlls[-1].name}")
    python_tag = f"python{dll_match.group(1)}"
    if python_tag != f"python{sys.version_info.major}{sys.version_info.minor}":
        raise RuntimePackageError(
            f"Build Python {sys.version_info.major}.{sys.version_info.minor} does not match "
            f"runtime DLL {versioned_dlls[-1].name}"
        )

    output.mkdir(parents=True, exist_ok=False)
    for filename in ("python.exe", "python3.dll", versioned_dlls[-1].name, "LICENSE.txt"):
        source = python_home / filename
        if source.is_file():
            shutil.copy2(source, output / filename)
    for source in python_home.glob("vcruntime*.dll"):
        shutil.copy2(source, output / source.name)

    shutil.copytree(dlls, output / "DLLs")
    shutil.copytree(
        lib,
        output / "Lib",
        ignore=shutil.ignore_patterns("site-packages"),
    )
    (output / "Lib" / "site-packages").mkdir()
    tcl = python_home / "tcl"
    if tcl.is_dir():
        shutil.copytree(tcl, output / "tcl")

    pth = output / f"{python_tag}._pth"
    pth.write_text(".\nDLLs\nLib\nLib/site-packages\n", encoding="ascii", newline="\n")
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _copy_distribution(dist: metadata.Distribution, site_packages: Path) -> None:
    files = dist.files
    if files is None:
        raise RuntimePackageError(f"Distribution has no install file list: {dist.metadata.get('Name')}")

    source_root = Path(dist.locate_file("")).resolve()
    if source_root.name.casefold() != "site-packages":
        raise RuntimePackageError(f"Distribution is not installed in site-packages: {source_root}")
    for relative_file in files:
        parts = Path(str(relative_file)).parts
        if Path(str(relative_file)).suffix.casefold() == ".pth":
            continue
        if ".." in parts and any(part.casefold() == "scripts" for part in parts):
            # Wheel console-script launchers are installed outside site-packages;
            # the Tauri app invokes Python modules directly and never needs them.
            continue
        source = Path(dist.locate_file(relative_file)).resolve()
        try:
            relative = source.relative_to(source_root)
        except ValueError as exc:
            raise RuntimePackageError(f"Distribution file escapes its site-packages root: {relative_file}") from exc
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimePackageError(f"Invalid distribution file path: {relative_file}")
        destination = site_packages / relative
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def build_runtime(
    python_home: Path,
    output: Path,
    requirements_file: Path | Iterable[Path],
    *,
    distributions: Iterable[metadata.Distribution] | None = None,
) -> dict:
    """Create a clean, isolated runtime tree; output must not already exist."""
    python_home = Path(python_home).resolve()
    output = Path(output).resolve()
    requirements_files = (
        [Path(requirements_file)]
        if isinstance(requirements_file, (str, Path))
        else [Path(path) for path in requirements_file]
    )
    requirements = [
        requirement
        for path in requirements_files
        for requirement in load_runtime_requirements(path)
    ]
    installed = list(metadata.distributions() if distributions is None else distributions)
    closure = resolve_distribution_closure(requirements, installed)

    python_version = _copy_python_files(python_home, output)
    site_packages = output / "Lib" / "site-packages"
    for dist in closure:
        _copy_distribution(dist, site_packages)

    manifest = {
        "pythonVersion": python_version,
        "packages": {
            canonicalize_name(dist.metadata["Name"]): dist.version
            for dist in closure
        },
    }
    (output / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, action="append")
    args = parser.parse_args(argv)

    try:
        requirements = args.requirements or [Path("requirements-runtime.txt")]
        manifest = build_runtime(Path(sys.base_prefix), args.output, requirements)
    except (OSError, RuntimePackageError) as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
