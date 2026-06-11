from .base import Settings

class DevSettings(Settings):
    DEBUG: bool = True

settings = DevSettings()
