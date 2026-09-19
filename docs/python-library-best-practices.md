# Python library design & packaging checklist (2026)

Primary sources only. Each item cites the document that owns the claim. Where sources
disagree or a practice has no primary-source backing, that is called out explicitly
rather than silently resolved.

---

## 1. Public API surface (`__init__.py`, `__all__`, re-exports, privacy)

- **Imports are private by default; re-export is opt-in.** The typing spec states plainly:
  "Imported symbols are considered private by default." Only three forms make a name
  part of the public interface: `import X as X`, `from Y import X as X`, and
  `from Y import *` (governed by `__all__`).
  — https://typing.python.org/en/latest/spec/distributing.html
  *(Note: this content lives at `typing.python.org`; `typing.readthedocs.io/.../distributing.html`
  302-redirects there — cite the resolved URL, not the redirect origin.)*
- **`mypy --strict` already enforces this.** `--strict` enables `--no-implicit-reexport`
  (confirmed via `mypy --help`: "Strict mode... --no-implicit-reexport..."). vernier's
  `pyproject.toml` sets `[tool.mypy] strict = true`, so a bare
  `from .run import run_ablate` in `__init__.py` is **not** just bad style — mypy will
  already refuse to consider it re-exported for downstream consumers. Use
  `from .run import run_ablate as run_ablate`, or import normally and list the name in
  `__all__` (mypy documents both as valid). — https://mypy.readthedocs.io/en/stable/command_line.html
- **Declare `__all__` explicitly in every public module, including `__init__.py`.**
  PEP 8: "modules should explicitly declare the names in their public API using the
  `__all__` attribute. Setting `__all__` to an empty list indicates that the module has
  no public API." — https://peps.python.org/pep-0008/
- **Prefix internal names with a single leading underscore, even under `__all__`.**
  PEP 8: "Even with `__all__` set appropriately, internal interfaces... should still be
  prefixed with a single leading underscore," and "An interface is also considered
  internal if any containing namespace (package, module or class) is considered
  internal." — https://peps.python.org/pep-0008/
- **Underscore-prefixed *modules* are excluded from a typed package's public interface
  wholesale.** The typing spec: submodules are importable "unless the file name begins
  with an underscore" — i.e. `_internal.py` is invisible to type checkers resolving the
  public interface, distinct from a merely underscore-prefixed *name* inside a public
  module. — https://typing.python.org/en/latest/spec/distributing.html
- **`from M import *` already skips underscore names** at the language level (PEP 8
  quoting the interpreter behavior: "`from M import *` does not import objects whose
  names start with an underscore"), independent of `__all__`.
  — https://peps.python.org/pep-0008/
- **Historical origin of `import X as X`, noted but not the citation to use**: the
  convention traces to PEP 484's stub-file rules, but PEP 484 predates the typing spec's
  extraction of this text into a living document. Cite the typing spec above for current
  behavior; PEP 484 is provenance, not the authority.

## 2. src-layout, PEP 621 metadata, uv/hatchling specifics

- **src-layout forces the installed package to be used, not the working tree.** Python
  Packaging User Guide: "The src layout helps prevent accidental usage of the
  in-development copy of the code" and "The src layout requires installation of the
  project to be able to run its code, and the flat layout does not."
  — https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
- **Caveat or contested-adjacent point**: the same guide notes "a command-line interface
  cannot be run directly from the source tree [under src-layout], but requires
  installation of the package in Development Mode" — i.e. `uv run` / editable installs
  are mandatory during development, not optional convenience. vernier already uses
  src-layout, so this is satisfied; keep using `uv run vernier ...` rather than
  `python src/vernier/cli.py`. — same URL as above.
- **`name` is the only field that can never be `dynamic`; `version` almost always is.**
  PEP 621: a build backend "MUST raise an error if the metadata specifies the `name` in
  `dynamic`," and for other required fields, "the metadata MUST specify the field
  statically or list it in `dynamic`." — https://peps.python.org/pep-0621/
- **`[build-system]` is strongly recommended even though technically optional.**
  Python Packaging User Guide, writing-pyproject-toml guide.
  — https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- **uv's own backend (`uv_build`) expects src-layout by default**: "a single root module
  is expected at `src/<package_name>/__init__.py`," with the package name normalized
  (lowercased, dots/dashes → underscores). It is pure-Python only — no extension
  modules. — https://docs.astral.sh/uv/concepts/build-backend/
- **Verified empirically for this project**: `uv build` on vernier's current
  `pyproject.toml` (`uv_build>=0.9.7,<0.10.0`) produces a wheel containing
  `vernier/py.typed` — uv_build includes it automatically because it lives inside
  `src/vernier/`; no extra config needed. (uv itself warned during the build that the
  pin `>=0.9.7,<0.10.0` doesn't cover the installed uv 0.12.8 — see the "Applying this to
  vernier" section.)
- **Under hatchling** (relevant if vernier ever switches backends), `py.typed` is *not*
  automatic to the same degree; Hatch's build docs describe `artifacts` (for
  VCS-ignored generated files) and `force-include` (explicit path mapping) as the
  mechanisms to guarantee a data file lands in the wheel.
  — https://hatch.pypa.io/latest/config/build/
- **`[project.scripts]` is the standard entry-point table for console commands** and
  installers turn each entry into a wrapper that does the equivalent of
  `sys.exit(main())`. — https://packaging.python.org/en/latest/specifications/entry-points/

## 3. PEP 561 (`py.typed`) and typed-library distribution

- **The marker file is mandatory and its scope is recursive.** PEP 561: "Package
  maintainers who wish to support type checking of their code MUST add a marker file
  named `py.typed` to their package," and "if a top-level package includes it, all its
  sub-packages MUST support type checking as well." — https://peps.python.org/pep-0561/
- **Placement**: at the top level of the *importable* package directory —
  `src/vernier/py.typed` — which is exactly where vernier already has it.
- **It must ship in the built wheel, not just the source tree.** PEP 561's own packaging
  example ("maintainers can use existing packaging options such as `package_data` in
  distutils") is dated — `distutils`/`package_data` is not how modern backends
  (uv_build, hatchling, PDM) are configured. Treat the *requirement* (the file must be
  present in the installed distribution) as binding and the *mechanism* named in the PEP
  as stale; consult your backend's docs instead (see §2). This is a case of a primary
  source itself being outdated, not a conflict between two sources.
- **Downstream effect**: once present, "the types bundled with the package SHOULD be
  used" by consuming type checkers (per PEP 561's resolution-order language) — this is
  what makes vernier's dataclasses and `JevClient` Protocol usable with full type
  information by anyone who does `pip install vernier` and runs mypy/pyright against
  their own code. — https://peps.python.org/pep-0561/

## 4. Versioning: PEP 440, semver, `__version__`, `importlib.metadata`

- **PEP 440 is the format PyPI/pip actually parse**: `[N!]N(.N)*[{a|b|rc}N][.postN][.devN]`,
  with ordering `.devN, aN, bN, rcN, <no suffix>, .postN`.
  — https://peps.python.org/pep-0440/
- **PEP 440 encourages, but does not require, semver.** Direct quote: "The
  'Major.Minor.Patch' aspects of semantic versioning are fully compatible with the
  version scheme defined in this PEP, and abiding by these aspects is encouraged." It
  stops short of mandating semver's stricter compatibility guarantees.
  — https://peps.python.org/pep-0440/
- **Semantic Versioning itself (not a Python PEP, but the source semver.org owns)**:
  "MAJOR version when you make incompatible API changes," "MINOR... backward compatible
  manner," "PATCH... backward compatible bug fixes." — https://semver.org/
  *(Flagging explicitly: semver.org is the de facto standard used by convention across
  the Python ecosystem, but it is not a PEP and PEP 440 does not incorporate it by
  reference — treat "follow semver" as a project choice layered on top of PEP 440's
  syntax, not a packaging requirement.)*
- **Single-source-of-truth for `__version__`**: `importlib.metadata.version()` "return[s]
  the installed distribution package version for the named distribution package," and
  raises `PackageNotFoundError` if it isn't installed.
  — https://docs.python.org/3/library/importlib.metadata.html
- **The recommendation to keep `__version__` and the installed distribution's metadata
  in sync, verified by a test, is the Packaging User Guide's, not `importlib.metadata`'s**:
  "the runtime `__version__` attribute on the import package [should] report the same
  version specifier as `importlib.metadata.version()` reports," and projects should
  "include an automated test case that ensures `import_name.__version__` and
  `importlib.metadata.version("dist-name")` report the same value." The guide does not
  hand you a canonical code snippet — the `try/except PackageNotFoundError` idiom is a
  common pattern built from `importlib.metadata`'s documented exception, not itself
  something either page shows verbatim, so treat it as a reasonable implementation of
  the guide's requirement rather than a quoted example.
  — https://packaging.python.org/en/latest/discussions/single-source-version/
- **Tension worth surfacing**: computing `__version__` via `importlib.metadata.version()`
  at *import time* of `vernier/__init__.py` is metadata I/O every time the package is
  imported — in mild conflict with "avoid import-time side effects" (§6). PEP 562's
  module-level `__getattr__` is the primary-source mechanism to make this lazy: define
  `__getattr__(name)` in `__init__.py` that resolves `"__version__"` only on first
  access, rather than computing it eagerly at module load.
  — https://peps.python.org/pep-0562/

## 5. Library core vs. CLI as a thin adapter

- **`[project.scripts]`** is the standard, backend-agnostic way to register a console
  entry point (`vernier = "vernier.cli:main"` — already correct in vernier's
  `pyproject.toml`). — https://packaging.python.org/en/latest/specifications/entry-points/
- **Optional dependency extras** for CLI-only requirements (argument parsing add-ons,
  rich output, etc.) go in `[project.optional-dependencies]`, keyed by extra name,
  values as PEP 508 dependency strings — not relevant yet for vernier since it has zero
  runtime dependencies, but this is the mechanism if the CLI ever needs one the library
  core doesn't. — https://peps.python.org/pep-0621/ (schema),
  https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ (usage)
- **Entry points tied to extras are explicitly discouraged now**: the entry-points spec
  says "Using extras for an entry point is no longer recommended. Consumers should
  support parsing them from existing distributions, but may then ignore them." Don't
  gate `[project.scripts]` behind an extra. — https://packaging.python.org/en/latest/specifications/entry-points/
- **No PEP or first-party doc prescribes "CLI as thin adapter" as an architecture rule**
  — this is a design convention, not a packaging specification. It follows from PEP 621
  giving CLI registration (`[project.scripts]`) and library import (`[project]`
  itself) two entirely separate, decoupled mechanisms: nothing about the packaging
  metadata requires or forbids CLI logic living inside the library modules, so the
  separation is a maintainability choice you're making, not one the standards impose.

## 6. Import-time side effects and dependency injection

- **No primary Python source (PEP, packaging.python.org, or stdlib docs) specifies a
  rule against import-time side effects or prescribes dependency injection.** This is
  recorded here as a convention with no PEP/first-party citation, per the task's
  instruction to say so rather than pad with a secondary source.
- **The one closely-related primary mechanism is PEP 562** (module `__getattr__`/`__dir__`),
  which exists specifically to let `__init__.py` defer computation (e.g. lazy submodule
  imports, lazy `__version__`) instead of doing it unconditionally at import time — see
  the PEP's own lazy-submodule example. — https://peps.python.org/pep-0562/
- vernier already leans this way structurally: `JevClient` is a `Protocol` with two
  implementations (`HttpJevClient`, `StubJevClient`), which is dependency injection by
  construction — `run_ablate()` presumably takes a `JevClient` rather than constructing
  one itself. Keep that shape; it's what makes the "convention" concrete here even
  though no spec mandates it.

## 7. Exception hierarchy

- **Derive from `Exception`, directly or indirectly; name with an `Error` suffix.**
  Python tutorial: "Exceptions should typically be derived from the `Exception` class,
  either directly or indirectly," and "Most exceptions are defined with names that end
  in 'Error', similar to the naming of the standard exceptions."
  — https://docs.python.org/3/tutorial/errors.html
- **One base class per library that all library-raised errors inherit from** is not
  stated by this tutorial page verbatim, but follows directly from its guidance plus
  ordinary exception-handling semantics (a single `except LibraryError:` catches every
  intentional library error without swallowing unrelated bugs). vernier already does
  exactly this: `VernierError(Exception)` in `errors.py`, whose own docstring states the
  intent — "they all inherit from this one so a caller can catch everything vernier
  raises with a single except clause without also catching bugs in its own code."

## 8. Logging

- **Never log to the root logger; use `logging.getLogger(__name__)`.** Logging HOWTO:
  "It is strongly advised that you do not log to the root logger in your library.
  Instead, use a logger with a unique and easily identifiable name, such as the
  `__name__` for your library's top-level package or module."
  — https://docs.python.org/3/howto/logging.html
- **Attach a `NullHandler`, nothing else, at import time of the library's top-level
  logger.** Same page: "An instance of this handler could be added to the top-level
  logger of the logging namespace used by the library," and "It is strongly advised that
  you do not add any handlers other than `NullHandler` to your library's loggers...
  configuration of handlers is the prerogative of the application developer."
  — https://docs.python.org/3/howto/logging.html
- **Document the logger names you use** — the HOWTO explicitly asks library authors to
  do this so application developers can configure verbosity per-component.

## 9. I/O at the edges / pure core

- **No PEP or first-party Python doc states "keep I/O at the edges" as a rule.** Same
  situation as §6: recorded explicitly as a convention without a primary-source
  citation, not silently asserted as a standard.
- What *is* directly evidenced from the codebase itself: `types.py`'s own docstring
  states the intent precisely — "Everything here is frozen and free of I/O so that
  segmentation, perturbation, the API client and the statistics can be tested in
  isolation" — which is the same idea vernier has already adopted deliberately, just
  without a spec to point to.

## 10. Docstrings and deprecation policy

- **Docstring format**: PEP 257 — triple double quotes, `r"""..."""` if the text has
  backslashes; a one-liner is "a phrase ending in a period. It prescribes the function
  or method's effect as a command ('Do this', 'Return that'), not as a description";
  a multi-line docstring is "a summary line just like a one-line docstring, followed by
  a blank line, followed by a more elaborate description."
  — https://peps.python.org/pep-0257/
- **PEP 8 says docstrings are for the public surface**: "Docstrings are not necessary
  for non-public methods, but you should have a comment that describes what the method
  does." — https://peps.python.org/pep-0008/
- **`DeprecationWarning` vs `FutureWarning` — audience is the distinguishing factor, not
  severity.** `warnings` docs: `DeprecationWarning` is for warnings "intended for other
  Python developers" (and is "ignored by default, unless triggered by code in
  `__main__`"); `FutureWarning` is for warnings "intended for end users of applications
  written in Python." As a library, code paths that library-consuming *developers* need
  to fix should raise `DeprecationWarning`; a warning meant to reach the end user of an
  application built on vernier (rare for a library, more relevant if vernier code is
  itself embedded in a user-facing script) would be `FutureWarning`.
  — https://docs.python.org/3/library/warnings.html
- **Always pass `stacklevel` so the warning points at the caller, not at the library
  internals.** Docs example: `warnings.warn(message, DeprecationWarning, stacklevel=2)`,
  "This makes the warning refer to `deprecated_api`'s caller, rather than to the source
  of `deprecated_api` itself." — https://docs.python.org/3/library/warnings.html
- **No PEP specifies a formal deprecation *policy* (how long to keep a deprecated API,
  how many minor versions, etc.)** — that is a project-level decision layered on top of
  the `DeprecationWarning`/`FutureWarning` mechanism above, not something the stdlib or
  a PEP prescribes.

---

## Applying this to vernier

Concrete, scoped to the module list given (`types.py`, `segment.py`, `perturb.py`,
`filler.py`, `client.py`, `distance.py`, `noise.py`, `run.py`, `report.py`, `cli.py`,
plus the already-present `errors.py` and `py.typed`):

1. **Replace `__init__.py`'s content entirely.** It currently contains only a stray
   `main()` that prints `"Hello from vernier!"` — leftover `uv init` scaffolding with no
   relationship to the CLI's real entry point (`vernier.cli:main`, per
   `[project.scripts]`). Delete it; it's dead code sitting in the public namespace.

2. **Build the public surface with explicit re-exports, matching what `mypy --strict`
   already demands** (confirmed: `--strict` includes `--no-implicit-reexport`):
   ```python
   from .client import HttpJevClient as HttpJevClient
   from .client import JevClient as JevClient
   from .client import StubJevClient as StubJevClient
   from .errors import VernierError as VernierError
   from .run import Config as Config
   from .run import Report as Report
   from .run import run_ablate as run_ablate
   from .types import Mode as Mode
   from .types import Question as Question
   from .types import Segment as Segment
   from .types import SegmentKind as SegmentKind
   # ... other frozen value types from types.py as needed by callers

   __all__ = [
       "HttpJevClient", "JevClient", "StubJevClient",
       "VernierError",
       "Config", "Report", "run_ablate",
       "Mode", "Question", "Segment", "SegmentKind",
   ]
   ```
   Treat `run_ablate()`, the `JevClient` Protocol + its two implementations, the
   frozen value types in `types.py`, and `VernierError` as the public surface — that's
   the orchestration entrypoint, the DI seam, the data contract, and the error contract.

3. **Candidates to keep as implementation detail, not exported from `__init__.py`**:
   `segment.py`, `perturb.py`, `filler.py`, `distance.py`, `noise.py`, `report.py`. Their
   symbols aren't wrong to leave importable via `vernier.segment.SEGMENTERS` etc. for
   power users, but nothing from them should appear in `__all__` — under the typing
   spec's default-private rule this already holds unless you add explicit re-exports, so
   the main discipline is simply *not adding* re-exports for these, rather than adding
   underscore prefixes to the filenames (renaming would break `cli.py`'s existing
   `from .segment import SEGMENTERS`-style imports for no real gain, since PEP 8's
   underscore-module convention is about signaling non-guaranteed API, and these modules
   already read as implementation support by name).

4. **Fix the exception hierarchy inconsistency.** `cli.py` defines
   `class UsageError(Exception): pass`, not `class UsageError(VernierError)`, which
   contradicts `errors.py`'s own docstring claim that "they all inherit from this one."
   This is a judgment call, not an obvious bug: `UsageError` is arguably CLI-only
   (bad argv), and a library caller of `run_ablate()` should never see it, so it may
   belong outside the library's public error hierarchy entirely. Decide explicitly
   either way rather than leaving the contradiction implicit — either make it inherit
   `VernierError` (if it's meant to be catchable alongside library errors) or add a
   comment in `errors.py` noting the hierarchy is library-only and CLI errors are a
   separate, intentionally distinct concern.

5. **Add `__version__` to `__init__.py`** sourced from `importlib.metadata.version()`
   for the distribution name `"vernier"`, per the single-source-of-truth pattern —
   optionally deferred via PEP 562's module `__getattr__` if importing
   `importlib.metadata` at every `import vernier` is a cost worth avoiding for a
   zero-dependency CLI/library. Add the test the Packaging User Guide recommends:
   assert `vernier.__version__ == importlib.metadata.version("vernier")`.

6. **`py.typed` is already correctly placed and already ships.** Verified directly: a
   local `uv build` produced `vernier/py.typed` inside the wheel with no extra
   configuration — uv_build includes it automatically because it lives at
   `src/vernier/py.typed`. Nothing to change here; just don't lose it in a future
   backend migration (hatchling would need explicit `force-include` or `artifacts`
   config — see §2/§3).

7. **Observation, not required by this task's scope**: `uv build` emitted a warning that
   the pin `uv_build>=0.9.7,<0.10.0` in `pyproject.toml` doesn't cover the installed uv
   (0.12.8), and uv's own docs example shows a newer pin (`>=0.12.17,<0.13`). Worth a
   separate, deliberate bump — not touched here since it's outside this task's remit
   (only this Markdown file was to be created).

8. **Minor naming note, no action required**: `types.py` shadows the stdlib `types`
   module name. Harmless under Python 3's absolute-import default and vernier's
   `from __future__ import annotations` usage, but worth knowing if anyone later adds a
   script that does a bare `import types` inside the `vernier` package by mistake.

9. **Logging**: none of the ten modules currently appear to use `logging` (not verified
   exhaustively here, out of scope for this research task). If/when added — e.g. in
   `client.py` around HTTP calls — follow §8 exactly: `logging.getLogger(__name__)` per
   module, a single `NullHandler()` attached once at the top-level `vernier` logger in
   `__init__.py`, never configured further inside the library.
