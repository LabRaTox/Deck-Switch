"""DECK//SWITCH — Steuerungssoftware für den Elgato Stream Deck+."""

#: Die Version der Anwendung — **die** Quelle, nicht eine von mehreren.
#:
#: ``pyproject.toml`` liest sie über ``[tool.setuptools.dynamic]`` hier
#: heraus, der Server schickt sie an die Oberfläche, und die Fassungen auf
#: der Rust-Seite (``Cargo.toml``) und in ``package.json`` werden von
#: ``tests/version_test.py`` dagegen geprüft. Eine Zahl, die an fünf Stellen
#: gepflegt werden muss, stimmt nach kurzer Zeit an drei davon nicht mehr.
__version__ = "1.0.0"
