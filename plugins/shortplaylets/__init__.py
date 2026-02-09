"""
Direct Short Play Scraper Plugin for MoviePilot
基于 MoviePilot 插件开发规范重构
"""

import os
import json
import requests
from threading import Thread
from urllib.parse import unquote

# 注意：根据文档，必须从 app.plugins 导入 PluginModule
from app.plugins import _PluginBase, PluginDescriptor
from app.core.config import settings
from app.utils.http import RequestUtils
from app.log import logger
from app.schemas import NotificationType
from app.utils.singleton import Singleton


class Directshortplayscraper(_PluginBase, metaclass=Singleton):
    # 插件元数据 (会被 PluginManager 读取)
    plugin_name = "DirectShortPlayScraper"
    plugin_desc = "直接从短剧站点抓取元数据，支持PT/通用双源"
    plugin_icon = "Amule_B.png"
    plugin_color = "#E74C3C"
    plugin_version = "1.2"
    plugin_author = "loong"
    plugin_config_prefix = "direct_short_play_"
    # 插件排序，如果有Web界面会用到
    plugin_order = 15
    # 权限级别
    auth_level = 1

    # 内部属性
    _active = False
    _pt_api_url = ""
    _pt_api_key = ""
    _general_site = "hongguo"
    _monitor_dirs = ""
    _cron = ""

    # 通用站点配置
    GENERAL_SITES = {
        "hongguo": {"name": "红果短剧", "search_url": "https://api.hongguo.com/search"},
        "mori": {"name": "末日", "search_url": "https://api.mori.com/search"} 
    }

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置
        """
        if config:
            self._active = config.get("enabled")
            self._pt_api_url = config.get("pt_api_url", "")
            self._pt_api_key = config.get("pt_api_key", "")
            self._general_site = config.get("general_site", "hongguo")
            self._monitor_dirs = config.get("monitor_dirs", "")
            self._cron = config.get("cron", "")

        # 无论配置如何，先停止现有任务
        self.stop_service()

        # 启动服务
        if self._active:
            # 启动定时任务
            if self._cron:
                self.start_scheduler()
            
            # 如果有立即运行标志，开启新线程执行
            if config and config.get("onlyonce"):
                # 重置 onlyonce 标志
                self.update_config({
                    "enabled": self._active,
                    "pt_api_url": self._pt_api_url,
                    "pt_api_key": self._pt_api_key,
                    "general_site": self._general_site,
                    "monitor_dirs": self._monitor_dirs,
                    "cron": self._cron,
                    "onlyonce": False
                })
                # 开启线程
                Thread(target=self.scrape_task, daemon=True).start()

    def scrape_task(self):
        """
        核心刮削任务逻辑
        """
        logger.info("【DirectShortPlayScraper】开始执行短剧刮削任务...")
        
        if not self._monitor_dirs:
            logger.warn("【DirectShortPlayScraper】未配置监控目录，跳过")
            return

        # 分割多目录
        directories = [d.strip() for d in self._monitor_dirs.split("\n") if d.strip()]
        
        for dir_path in directories:
            if not os.path.exists(dir_path):
                continue
                
            # 遍历一级目录（短剧名称）
            for item in os.scandir(dir_path):
                if not item.is_dir():
                    continue
                    
                shortplay_title = item.name
                logger.info(f"【DirectShortPlayScraper】正在处理: {shortplay_title}")
                
                # 1. 尝试 PT 站点
                meta_data = None
                if self._pt_api_url and self._pt_api_key:
                    meta_data = self._search_pt(shortplay_title)
                
                # 2. PT 失败，尝试通用站点
                if not meta_data and self._general_site:
                    meta_data = self._search_general(shortplay_title, self._general_site)
                
                # 3. 写入文件
                if meta_data:
                    self._save_nfo_and_poster(item.path, shortplay_title, meta_data)
                    self.send_message(
                        title="短剧刮削成功",
                        text=f"《{shortplay_title}》元数据已更新",
                        mtype=NotificationType.Plugin
                    )
                else:
                    logger.warn(f"【DirectShortPlayScraper】未找到元数据: {shortplay_title}")

    def _search_pt(self, title: str) -> dict:
        """
        搜索PT站点 (模拟)
        """
        # TODO: 根据实际PT API实现
        logger.info(f"【PT】正在搜索: {title}")
        # 模拟返回
        return {"title": title, "plot": "PT剧情简介", "poster_url": None}

    def _search_general(self, title: str, site: str) -> dict:
        """
        搜索通用站点
        """
        site_info = self.GENERAL_SITES.get(site)
        if not site_info:
            return None
            
        logger.info(f"【{site_info['name']}】正在搜索: {title}")
        # TODO: 实现真实的HTTP请求和解析
        return {"title": title, "plot": "通用剧情简介", "poster_url": None}

    def _save_nfo_and_poster(self, dir_path: str, title: str, meta: dict):
        """
        保存 NFO 和海报
        """
        # 生成 NFO
        nfo_path = os.path.join(dir_path, "movie.nfo")
        nfo_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
    <title>{title}</title>
    <plot><![CDATA[{meta.get('plot', '')}]]></plot>
</movie>
        """
        try:
            with open(nfo_path, 'w', encoding='utf-8') as f:
                f.write(nfo_content)
            logger.debug(f"NFO已生成: {nfo_path}")
        except Exception as e:
            logger.error(f"写入NFO失败: {e}")

    def get_state(self) -> bool:
        """
        插件状态
        """
        return self._active

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程命令 (如果需要)
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        定义API接口 (如果需要)
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册后台服务 (定时任务)
        """
        # 根据文档，这里返回服务列表，框架会自动管理
        if self._active and self._cron:
            return [
                {
                    "id": "DirectShortPlayScraper",
                    "name": "短剧刮削服务",
                    "trigger": "interval",
                    "minutes": int(self._cron) * 60, # 转换为分钟
                    "func": self.scrape_task
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        配置页面
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即运行一次'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '间隔(小时)',
                                            'placeholder': '留空则不自动运行'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pt_api_url',
                                            'label': 'PT站点API地址'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pt_api_key',
                                            'label': 'PT站点API Key'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'general_site',
                                            'label': '通用站点',
                                            'items': [
                                                {'title': '红果短剧', 'value': 'hongguo'},
                                                {'title': '末日', 'value': 'mori'}
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'monitor_dirs',
                                            'label': '监控目录',
                                            'rows': 3
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "pt_api_url": "",
            "pt_api_key": "",
            "general_site": "hongguo",
            "monitor_dirs": "",
            "cron": "",
            "onlyonce": False
        }

    def stop_service(self):
        """
        停止服务
        """
        # 如果有全局的 scheduler 或 thread，这里进行清理
        # 由于我们使用了框架的 get_service，通常不需要手动停止定时器
        pass

# --- 注册插件 ---
# 根据文档，通常需要实例化或注册
DirectShortPlayScraper = Directshortplayscraper()
