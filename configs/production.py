from .base import Settings

class ProdSettings(Settings):
    DEBUG: bool = False

settings = ProdSettings()
