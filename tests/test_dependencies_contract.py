"""Contract: optional/heavy dependencies are lazy and declared as extras.

Guarantees:
  * importing the extractor registry does NOT pull heavy optional deps;
  * every extractor that needs a 3rd-party package has a matching extra in pyproject;
  * core modules import on base dependencies alone."""
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# extractor name -> required 3rd-party pip package (None = covered by core deps)
EXTRACTOR_PKG = {
    "tika": None, "passthrough": None, "vision_llm": None,
    "mistral_ocr": None, "unstructured": None, "llamaparse": None,
    "docling": "docling",
    "marker": "marker-pdf",
    "azure_di": "azure-ai-documentintelligence",
    "aws_textract": "boto3",
    "google_docai": "google-cloud-documentai",
}


def _optional_deps() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    return " ".join(pkg for vals in extras.values() for pkg in vals).lower()


def test_every_extractor_has_declared_extra():
    from tome.extract.registry import _BUILDERS
    declared = _optional_deps()
    for name in _BUILDERS:
        pkg = EXTRACTOR_PKG.get(name)
        if pkg:
            assert pkg.lower() in declared, f"extractor '{name}' needs '{pkg}' declared as an extra"


def test_registry_import_is_lazy():
    # In a clean process, importing the registry must not import heavy optional deps.
    code = (
        "import sys, tome.extract.registry as r;"
        "heavy={'docling','boto3','marker','azure','google','sentence_transformers'};"
        "loaded=sorted(m for m in heavy if m in sys.modules);"
        "print('LOADED', loaded);"
        "sys.exit(1 if loaded else 0)"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                         capture_output=True, text=True)
    assert res.returncode == 0, f"registry import is not lazy: {res.stdout}{res.stderr}"


def test_core_modules_import_on_base_deps():
    for mod in ("tome.pipeline.run", "tome.store", "api.main", "mcp_server.server"):
        __import__(mod)
