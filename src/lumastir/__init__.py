"""Lumastir. Importing the package never imports Raspberry Pi drivers."""

__version__ = "0.2.0"


def __getattr__(name):
    if name == "LumaController":
        from .controller import LumaController

        return LumaController
    raise AttributeError(name)
