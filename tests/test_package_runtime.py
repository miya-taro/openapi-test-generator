from pathlib import Path, PurePosixPath

import pytest
from packaging.requirements import Requirement

from scripts.package_runtime import (
    RuntimePackageError,
    build_runtime,
    load_runtime_requirements,
    resolve_distribution_closure,
)


class FakeDistribution:
    def __init__(self, name: str, version: str, root: Path, files=(), requires=()):
        self.metadata = {"Name": name}
        self.version = version
        self.root = root
        self.files = [PurePosixPath(file) for file in files]
        self.requires = list(requires)

    def locate_file(self, path):
        return self.root / path


def _distribution(name: str, version: str, requires: list[str] | None = None):
    return FakeDistribution(name, version, Path("C:/site-packages"), requires=requires or [])


def test_load_runtime_requirements_skips_comments_and_blank_lines(tmp_path: Path):
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("""# Runtime-only dependencies
requests>=2.31

PyYAML>=6.0  # database scenario format
""", encoding="utf-8")

    parsed = load_runtime_requirements(requirements)

    assert [requirement.name for requirement in parsed] == ["requests", "PyYAML"]
    assert str(parsed[0].specifier) == ">=2.31"


def test_resolve_distribution_closure_includes_transitives_once_and_skips_inactive_markers():
    distributions = [
        _distribution("api-engine", "1.4", ["shared-lib>=2", 'doc-helper; extra == "docs"']),
        _distribution("Requests", "2.34.2", ["shared-lib>=2"]),
        _distribution("shared_lib", "2.1"),
        _distribution("doc-helper", "9.0"),
    ]

    resolved = resolve_distribution_closure(
        [Requirement("api-engine>=1"), Requirement("requests>=2.31")],
        distributions,
    )

    assert [item.metadata["Name"].lower().replace("_", "-") for item in resolved] == [
        "api-engine",
        "requests",
        "shared-lib",
    ]


@pytest.mark.parametrize(
    ("requirement", "distributions", "message"),
    [
        ("missing-package>=1", [], "not installed"),
        ("requests>=9", [_distribution("requests", "2.34.2")], "does not satisfy"),
    ],
)
def test_resolve_distribution_closure_rejects_missing_or_incompatible_versions(
    requirement: str, distributions: list, message: str
):
    with pytest.raises(RuntimePackageError, match=message):
        resolve_distribution_closure([Requirement(requirement)], distributions)


def test_build_runtime_copies_only_required_packages_and_writes_isolated_search_path(tmp_path: Path):
    python_home = tmp_path / "python"
    site_packages = python_home / "Lib" / "site-packages"
    output = tmp_path / "runtime"
    requirements = tmp_path / "requirements-runtime.txt"
    exploration_requirements = tmp_path / "requirements-exploration.txt"
    requirements.write_text("requests>=2.31\n", encoding="utf-8")
    exploration_requirements.write_text("schemathesis>=4.25\n", encoding="utf-8")
    for relative, content in {
        "python.exe": "interpreter",
        "python3.dll": "stable dll",
        "python312.dll": "versioned dll",
        "vcruntime140.dll": "runtime dll",
        "DLLs/_socket.pyd": "socket extension",
        "Lib/encodings/__init__.py": "encoding module",
        "Lib/site-packages/requests/__init__.py": "requests module",
        "Lib/site-packages/requests-2.34.2.dist-info/METADATA": "Name: requests\n",
        "Lib/site-packages/idna/__init__.py": "idna module",
        "Lib/site-packages/idna-3.19.dist-info/METADATA": "Name: idna\n",
        "Lib/site-packages/schemathesis/__init__.py": "exploration module",
        "Lib/site-packages/dev_only/__init__.py": "development-only module",
    }.items():
        path = python_home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    distributions = [
        FakeDistribution(
            "requests",
            "2.34.2",
            site_packages,
            [
                "requests/__init__.py",
                "requests-2.34.2.dist-info/METADATA",
                "../../Scripts/requests.exe",
            ],
            ["idna>=3"],
        ),
        FakeDistribution(
            "idna",
            "3.19",
            site_packages,
            ["idna/__init__.py", "idna-3.19.dist-info/METADATA"],
        ),
        FakeDistribution(
            "schemathesis",
            "4.25.0",
            site_packages,
            ["schemathesis/__init__.py"],
            ["idna>=3"],
        ),
        FakeDistribution(
            "dev-only",
            "1.0",
            site_packages,
            ["dev_only/__init__.py"],
        ),
    ]

    manifest = build_runtime(
        python_home,
        output,
        [requirements, exploration_requirements],
        distributions=distributions,
    )

    assert (output / "python.exe").read_text(encoding="utf-8") == "interpreter"
    assert (output / "Lib/encodings/__init__.py").is_file()
    assert (output / "Lib/site-packages/requests/__init__.py").is_file()
    assert (output / "Lib/site-packages/idna/__init__.py").is_file()
    assert (output / "Lib/site-packages/schemathesis/__init__.py").is_file()
    assert not (output / "Lib/site-packages/dev_only/__init__.py").exists()
    assert (output / "python312._pth").read_text(encoding="utf-8").splitlines() == [
        ".",
        "DLLs",
        "Lib",
        "Lib/site-packages",
    ]
    assert manifest["packages"] == {
        "idna": "3.19",
        "requests": "2.34.2",
        "schemathesis": "4.25.0",
    }
