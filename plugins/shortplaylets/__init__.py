"""
ShortPlay Site Scraper
利用 MoviePilot 站点管理功能，直接调用已配置站点的 Cookie 进行刮削
"""

import os
import re
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple
from app.plugins import _PluginBase
from app.core.config import settings
from app.log import logger
from app.schemas import NotificationType
from app.db.site_oper import SiteOper
from app.helper.sites import SitesHelper
from app.utils.http import RequestUtils
from app.utils import SystemUtils
from app.utils.singleton import Singleton
from app.utils.dom import DomUtils
from bs4 import BeautifulSoup
import urllib.parse

# 全局单例锁
lock = threading.Lock()

class Shortplaysitescraper(_PluginBase, metaclass=Singleton):
    # 插件定义
    plugin_name = "短剧站点刮削"
    plugin_desc = "使用已配置的站点(Cookie)进行刮削，无需重复配置"
    plugin_icon = "ShortPlay.png"
    plugin_version = "1.0"
    plugin_author = "loong"
    plugin_config_prefix = "short_play_site_"
    plugin_order = 16
    auth_level = 1

    # 内部变量
    _active = False
    _monitor_dirs = ""
    _cron = ""
    _onlyonce = False
    _sites = []  # 存储用户勾选的站点ID
    _exclude_keywords = "" # 排除关键词

    # 调度器
    _scheduler = None
    _observer = []

    def init_plugin(self, config: dict = None):
        if config:
            self._active = config.get("enabled")
            self._monitor_dirs = config.get("monitor_dirs", "")
            self._cron = config.get("cron", "")
            self._onlyonce = config.get("onlyonce", False)
            self._sites = config.get("sites", []) # 这里拿到的是站点ID列表
            self._exclude_keywords = config.get("exclude_keywords", "")

        # 停止现有任务
        self.stop_service()

        # 启动任务
        if self._active or self._onlyonce:
            # 初始化定时器
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            
            # 立即运行一次
            if self._onlyonce:
                logger.info("【ShortPlaySiteScraper】立即运行一次")
                self._onlyonce = False
                self.update_config({
                    "enabled": self._active,
                    "monitor_dirs": self._monitor_dirs,
                    "cron": self._cron,
                    "onlyonce": False,
                    "sites": self._sites,
                    "exclude_keywords": self._exclude_keywords
                })
                # 开启线程
                threading.Thread(target=self.scrape_media, daemon=True).start()

            # 周期运行
            if self._cron:
                try:
                    self._scheduler.add_job(
                        func=self.scrape_media,
                        trigger='interval',
                        hours=int(self._cron),
                        name="短剧站点刮削"
                    )
                    if not self._scheduler.running:
                        self._scheduler.start()
                except Exception as e:
                    logger.error(f"定时器设置失败: {e}")

    def scrape_media(self):
        """
        核心刮削逻辑
        """
        if not self._monitor_dirs:
            logger.warn("【ShortPlaySiteScraper】未配置监控目录")
            return

        # 获取所有启用的站点信息 (用于后续匹配)
        all_sites = SiteOper().list_order_by_pri()
        enabled_site_names = [site.name for site in all_sites if str(site.id) in self._sites]

        logger.info(f"【ShortPlaySiteScraper】开始刮削，目标站点: {enabled_site_names}")
        
        # 遍历监控目录
        monitor_dirs = [d.strip() for d in self._monitor_dirs.split("\n") if d.strip()]
        for monitor_dir in monitor_dirs:
            if not os.path.exists(monitor_dir):
                continue
                
            # 遍历一级子目录 (短剧名)
            for dir_name in os.listdir(monitor_dir):
                dir_path = os.path.join(monitor_dir, dir_name)
                if not os.path.isdir(dir_path):
                    continue

                # 检查排除关键词
                if self._exclude_keywords and any(keyword in dir_name for keyword in self._exclude_keywords.split(",")):
                    continue

                logger.info(f"【ShortPlaySiteScraper】正在处理: {dir_name}")

                # 1. 先检查本地是否有 NFO (PT 站点通常有)
                nfo_path = os.path.join(dir_path, "movie.nfo")
                if os.path.exists(nfo_path):
                    logger.info(f"【ShortPlaySiteScraper】{dir_name} 已存在 NFO，跳过")
                    continue

                # 2. 尝试从配置的站点搜索
                success = False
                for site_id in self._sites:
                    site = next((s for s in all_sites if s.id == int(site_id)), None)
                    if not site or not site.cookie:
                        continue

                    logger.info(f"【ShortPlaySiteScraper】尝试站点: {site.name}")
                    meta = self._search_site(site, dir_name)
                    if meta:
                        self._save_files(dir_path, dir_name, meta)
                        success = True
                        break

                if success:
                    logger.info(f"【ShortPlaySiteScraper】{dir_name} 刮削成功")
                    self.send_message(
                        title="短剧刮削成功",
                        text=f"《{dir_name}》元数据已更新",
                        mtype=NotificationType.Plugin
                    )
                else:
                    logger.warn(f"【ShortPlaySiteScraper】{dir_name} 所有站点刮削失败")

    def _search_site(self, site, keyword) -> Dict[str, str]:
        """
        模拟站点搜索 (需要根据具体站点HTML结构调整)
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': site.cookie
        }

        try:
            # 这里的搜索URL需要根据你的PT站点实际接口修改
            # 例如: pts 可能是 /torrents.php?search=keyword
            search_url = f"{site.url}/search?{urllib.parse.urlencode({'search': keyword})}"
            
            res = RequestUtils(headers=headers).get_res(search_url)
            if not res:
                return None

            # 解析 HTML (这里使用 BeautifulSoup 作为示例，比 lxml 更容错)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # TODO: 这里需要根据具体站点的 HTML 结构写解析逻辑
            # 例如查找包含剧名的第一个种子项
            item = soup.find('a', text=re.compile(keyword, re.I))
            if item:
                # 模拟获取详情页或直接提取信息
                # 这里简化处理，实际需要进入详情页抓取简介、海报等
                return {
                    "title": keyword,
                    "plot": f"来自 {site.name} 的剧情简介",
                    "poster_url": None # 如果站点有海报需要解析
                }
        except Exception as e:
            logger.error(f"站点 {site.name} 搜索失败: {e}")
        
        return None

    def _save_files(self, dir_path, title, meta):
        """
        保存 NFO 和海报
        """
        # 生成 NFO
        root = ET.Element("movie")
        ET.SubElement(root, "title").text = meta.get("title", title)
        ET.SubElement(root, "plot").text = meta.get("plot", "")
        
        tree = ET.ElementTree(root)
        nfo_path = os.path.join(dir_path, "movie.nfo")
        tree.write(nfo_path, encoding="utf-8", xml_declaration=True)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        定义插件配置表单
        """
        # 获取站点列表供下拉选择
        site_names = {}
        if SiteOper:
            # 获取所有站点
            db_sites = SiteOper().list_order_by_pri()
            site_names = {str(site.id): f"{site.name} ({site.url})" for site in db_sites}

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'monitor_dirs',
                                            'label': '监控目录',
                                            'placeholder': '每行一个目录',
                                            'rows': 3
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'sites',
                                            'label': '选择短剧站点',
                                            'multiple': True,
                                            'chips': True,
                                            'hint': '选择已在站点管理中配置好的短剧/PT站点',
                                            'persistent-hint': True
                                        },
                                        'items': [
                                            {'title': name, 'value': sid} for sid, name in site_names.items()
                                        ]
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude_keywords',
                                            'label': '排除关键词',
                                            'placeholder': '包含这些词的目录跳过刮削，用,分隔',
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '刮削间隔(小时)',
                                            'placeholder': '留空则不自动运行'
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
            "monitor_dirs": "",
            "sites": [],
            "exclude_keywords": "预告,花絮",
            "cron": "12"
        }

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册服务（如果需要被框架调度）
        """
        if self._active and self._cron:
            return [{
                "id": "ShortPlaySiteScraper",
                "name": "短剧站点刮削服务",
                "trigger": "interval",
                "hours": int(self._cron),
                "func": self.scrape_media
            }]
        return []

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止服务失败: {e}")

        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    pass
            self._observer = []
