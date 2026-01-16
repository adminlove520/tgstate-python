import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """
    应用程序设置。
    """
    BOT_TOKEN: Optional[str] = None
    CHANNEL_NAME: Optional[str] = None
    PASS_WORD: Optional[str] = None
    PICGO_API_KEY: Optional[str] = None # [可选] PicGo 上传接口的 API 密钥
    BASE_URL: str = "http://127.0.0.1:8000"
    MODE: str = "p" # p 代表公开模式, m 代表私有模式
    FILE_ROUTE: str = "/d/"
    HTTPS_PROXY: Optional[str] = None
    HTTP_PROXY: Optional[str] = None


@lru_cache()
def get_settings() -> Settings:
    """
    获取应用程序设置。

    此函数会被缓存，以避免在每个请求中都从环境中重新读取设置。
    """
    return Settings()

def get_active_password() -> Optional[str]:
    """
    获取当前有效的密码。
    优先从数据库读取，如果为空则回退到环境变量。
    """
    try:
        from .. import database

        db_settings = database.get_app_settings_from_db()
        password = (db_settings.get("PASS_WORD") or "").strip()
        if password:
            return password
    except Exception:
        pass

    return get_settings().PASS_WORD

def get_app_settings() -> dict:
    """
    获取当前生效的应用设置（数据库优先，环境变量兜底）。
    返回字段: BOT_TOKEN, CHANNEL_NAME, PASS_WORD, PICGO_API_KEY, BASE_URL
    """
    env = get_settings()
    try:
        from .. import database

        db_settings = database.get_app_settings_from_db()
    except Exception:
        db_settings = {}

    return {
        "BOT_TOKEN": (db_settings.get("BOT_TOKEN") or env.BOT_TOKEN),
        "CHANNEL_NAME": (db_settings.get("CHANNEL_NAME") or env.CHANNEL_NAME),
        "PASS_WORD": (db_settings.get("PASS_WORD") or env.PASS_WORD),
        "PICGO_API_KEY": (db_settings.get("PICGO_API_KEY") or env.PICGO_API_KEY),
        "BASE_URL": (db_settings.get("BASE_URL") or env.BASE_URL),
        "HTTPS_PROXY": (db_settings.get("HTTPS_PROXY") or env.HTTPS_PROXY),
        "HTTP_PROXY": (db_settings.get("HTTP_PROXY") or env.HTTP_PROXY),
    }
