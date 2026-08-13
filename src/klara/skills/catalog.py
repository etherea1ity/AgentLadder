"""Discover, resolve, and progressively read trusted Klara Skill packages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, Literal


SkillScope = Literal["built_in", "user", "project"]
_SCOPE_PRIORITY: dict[SkillScope, int] = {
    "built_in": 0,
    "user": 1,
    "project": 2,
}
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SkillCatalogError(ValueError):
    """Public, stable error raised for invalid or unavailable Skills."""


@dataclass(frozen=True)
class SkillDescriptor:
    """Metadata-only view of one resolved Skill version."""

    name: str
    description: str
    version: str
    scope: SkillScope
    source: str
    sha256: str
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    references: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, object]:
        """Return safe metadata without loading the Skill body."""

        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "scope": self.scope,
            "source": self.source,
            "sha256": self.sha256,
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "dependencies": list(self.dependencies),
            "references": list(self.references),
        }


@dataclass(frozen=True)
class SkillDocument:
    """Progressively loaded Skill body or referenced text."""

    descriptor: SkillDescriptor
    body: str
    reference: str | None = None

    def to_model_dict(self) -> dict[str, object]:
        """Return the validated model-visible document contract."""

        return {
            "name": self.descriptor.name,
            "version": self.descriptor.version,
            "scope": self.descriptor.scope,
            "sha256": self.descriptor.sha256,
            "reference": self.reference,
            "body": self.body,
        }


@dataclass(frozen=True)
class _SkillEntry:
    descriptor: SkillDescriptor
    root: Path
    body_path: Path


class SkillCatalog:
    """Resolve built-in, user, and project Skills with fixed precedence."""

    def __init__(
        self,
        entries: Iterable[_SkillEntry],
        *,
        allowed_tools: Iterable[str] = (),
        allowed_permissions: Iterable[str] = (),
        max_body_chars: int = 20_000,
        max_reference_chars: int = 12_000,
    ) -> None:
        if max_body_chars < 1 or max_reference_chars < 1:
            raise ValueError("skill document budgets must be positive")
        self._allowed_tools = frozenset(allowed_tools)
        self._allowed_permissions = frozenset(allowed_permissions)
        self._max_body_chars = max_body_chars
        self._max_reference_chars = max_reference_chars
        self._entries: dict[str, _SkillEntry] = {}
        self._shadowed: dict[str, list[SkillDescriptor]] = {}
        # Lower-precedence entries are retained as audit metadata while the
        # resolved mapping deterministically advances toward project scope.
        for entry in sorted(
            entries,
            key=lambda value: (
                value.descriptor.name,
                _SCOPE_PRIORITY[value.descriptor.scope],
                value.descriptor.source,
            ),
        ):
            previous = self._entries.get(entry.descriptor.name)
            if previous is not None:
                self._shadowed.setdefault(entry.descriptor.name, []).append(
                    previous.descriptor
                )
            self._entries[entry.descriptor.name] = entry

    @classmethod
    def discover(
        cls,
        *,
        built_in_root: Path | None,
        user_root: Path | None,
        project_root: Path | None,
        allowed_tools: Iterable[str] = (),
        allowed_permissions: Iterable[str] = (),
        max_body_chars: int = 20_000,
        max_reference_chars: int = 12_000,
    ) -> "SkillCatalog":
        """Discover Skill packages from the three supported scopes."""

        entries: list[_SkillEntry] = []
        # Scope order is explicit so discovery never depends on filesystem order.
        for scope, root in (
            ("built_in", built_in_root),
            ("user", user_root),
            ("project", project_root),
        ):
            if root is None or not root.exists():
                continue
            resolved_root = root.resolve()
            # Each child package contributes one SKILL.md document.
            for body_path in sorted(root.glob("*/SKILL.md")):
                try:
                    body_path.resolve().relative_to(resolved_root)
                except ValueError as exc:
                    raise SkillCatalogError("skill_package_outside_scope") from exc
                entries.append(_parse_entry(body_path, scope=scope))
        return cls(
            entries,
            allowed_tools=allowed_tools,
            allowed_permissions=allowed_permissions,
            max_body_chars=max_body_chars,
            max_reference_chars=max_reference_chars,
        )

    def list(self) -> tuple[SkillDescriptor, ...]:
        """Return only resolved metadata, never Skill bodies."""

        return tuple(self._entries[name].descriptor for name in sorted(self._entries))

    def shadowed(self, name: str) -> tuple[SkillDescriptor, ...]:
        """Return lower-precedence definitions hidden by the resolved Skill."""

        return tuple(self._shadowed.get(name, ()))

    def descriptor(self, name: str) -> SkillDescriptor:
        """Return resolved metadata for one normalized Skill name."""

        normalized = _normalize_name(name)
        entry = self._entries.get(normalized)
        if entry is None:
            raise SkillCatalogError("skill_not_found")
        return entry.descriptor

    def load(
        self,
        name: str,
        *,
        reference: str | None = None,
    ) -> SkillDocument:
        """Load one body/reference after dependency and permission validation."""

        descriptor = self.descriptor(name)
        entry = self._entries[descriptor.name]
        missing_dependencies = sorted(
            dependency
            for dependency in descriptor.dependencies
            if dependency not in self._entries
        )
        if missing_dependencies:
            raise SkillCatalogError(
                f"skill_dependency_missing:{','.join(missing_dependencies)}"
            )
        forbidden_tools = sorted(set(descriptor.tools) - self._allowed_tools)
        if forbidden_tools:
            raise SkillCatalogError(
                f"skill_tool_not_allowed:{','.join(forbidden_tools)}"
            )
        forbidden_permissions = sorted(
            set(descriptor.permissions) - self._allowed_permissions
        )
        if forbidden_permissions:
            raise SkillCatalogError(
                f"skill_permission_not_allowed:{','.join(forbidden_permissions)}"
            )
        if reference is None:
            path = entry.body_path
            limit = self._max_body_chars
        else:
            if reference not in descriptor.references:
                raise SkillCatalogError("skill_reference_not_declared")
            path = _safe_child(entry.root, reference)
            limit = self._max_reference_chars
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SkillCatalogError("skill_document_unreadable") from exc
        if len(body) > limit:
            raise SkillCatalogError("skill_document_too_large")
        return SkillDocument(
            descriptor=descriptor,
            body=_strip_frontmatter(body) if reference is None else body,
            reference=reference,
        )

    def public_summary(self) -> dict[str, object]:
        """Return metadata and deterministic conflict evidence for API/UI."""

        skills = []
        # Render one stable metadata record per resolved Skill.
        for descriptor in self.list():
            item = descriptor.to_public_dict()
            item["shadowed_scopes"] = [
                shadowed.scope for shadowed in self.shadowed(descriptor.name)
            ]
            skills.append(item)
        return {
            "schema_version": "klara.skills-catalog.v1",
            "precedence": ["project", "user", "built_in"],
            "body_loading": "on_demand",
            "skills": skills,
        }

    @property
    def catalog_sha256(self) -> str:
        """Return a stable hash of the resolved metadata catalog."""

        encoded = json.dumps(
            self.public_summary(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _parse_entry(path: Path, *, scope: SkillScope) -> _SkillEntry:
    """Parse one safe frontmatter contract without loading referenced files."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillCatalogError("skill_document_unreadable") from exc
    metadata, _ = _split_frontmatter(text)
    name = _normalize_name(metadata.get("name") or path.parent.name)
    description = metadata.get("description", "").strip()
    if not description:
        raise SkillCatalogError(f"skill_description_missing:{name}")
    version = metadata.get("version", "1.0.0").strip()
    if not version:
        raise SkillCatalogError(f"skill_version_missing:{name}")
    descriptor = SkillDescriptor(
        name=name,
        description=description,
        version=version,
        scope=scope,
        source=f"{scope}:{path.parent.name}",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        tools=_csv(metadata.get("tools", "")),
        permissions=_csv(metadata.get("permissions", "")),
        dependencies=_csv(metadata.get("dependencies", "")),
        references=_references(metadata.get("references", ""), path.parent),
    )
    return _SkillEntry(descriptor=descriptor, root=path.parent.resolve(), body_path=path)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse the deliberately small flat YAML subset used by Klara Skills."""

    if not text.startswith("---\n"):
        raise SkillCatalogError("skill_frontmatter_missing")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise SkillCatalogError("skill_frontmatter_unclosed")
    metadata: dict[str, str] = {}
    # Frontmatter is intentionally flat; nested executable config is rejected.
    for line in text[4:marker].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise SkillCatalogError("skill_frontmatter_invalid")
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, text[marker + 5 :].strip()


def _strip_frontmatter(text: str) -> str:
    """Return only instructions after validated metadata."""

    return _split_frontmatter(text)[1]


def _csv(value: str) -> tuple[str, ...]:
    """Normalize one comma-delimited frontmatter value."""

    return tuple(part.strip() for part in value.split(",") if part.strip())


def _references(value: str, root: Path) -> tuple[str, ...]:
    """Validate declared references as relative files inside the package."""

    references = _csv(value)
    # Every declared document must resolve within its immutable package root.
    for reference in references:
        _safe_child(root.resolve(), reference)
    return references


def _safe_child(root: Path, relative: str) -> Path:
    """Resolve a relative document path without allowing traversal/symlinks out."""

    candidate = Path(relative)
    if candidate.is_absolute():
        raise SkillCatalogError("skill_reference_outside_package")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise SkillCatalogError("skill_reference_outside_package") from exc
    if not resolved.is_file():
        raise SkillCatalogError("skill_reference_missing")
    return resolved


def _normalize_name(name: str) -> str:
    """Normalize and validate a model-requested Skill name."""

    normalized = name.strip().lower()
    if not _NAME_PATTERN.fullmatch(normalized):
        raise SkillCatalogError("skill_name_invalid")
    return normalized
