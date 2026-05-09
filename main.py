"""
AstrBot 随机图片发送插件
功能：在随机时间间隔内，向指定群聊随机发送图片
作者：XingYe
版本：1.3.0
"""

import asyncio
import os
import random
import base64
from pathlib import Path
from typing import Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import Context, Image, MessageChain, MessageEventResult, Star, register
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import PermissionType, PlatformAdapterType, command, permission_type


@register(
    "astrbot_plugin_random_image",
    "XingYe",
    "在随机时间间隔内向群聊随机发送图片",
    "1.3.0",
    "https://github.com/XingYe/astrbot_plugin_random_image"
)
class Main(Star):
    """随机图片发送插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig = None) -> None:
        """初始化插件"""
        super().__init__(context)
        self.context = context
        self.config = config or {}

        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))

        self._load_config()

        self._is_running = False
        self._background_task: Optional[asyncio.Task] = None

        self._sent_count = 0
        self._error_count = 0

        self._auto_start()

    def _load_config(self) -> None:
        """从配置文件加载参数"""
        raw_folder = self.config.get("image_folder", "images")

        if os.path.isabs(raw_folder):
            self.image_folder = raw_folder
        else:
            self.image_folder = os.path.join(self.plugin_dir, raw_folder)

        self.min_interval = max(1, int(self.config.get("min_interval", 18000)))
        self.max_interval = max(self.min_interval, int(self.config.get("max_interval", 36000)))

        self.target_group = self.config.get("target_group", "").strip()

        self.verbose_logging = self.config.get("verbose_logging", False)

        self._validate_config()

    def _validate_config(self) -> None:
        """验证配置参数的合法性"""
        if not self.target_group:
            logger.warning("⚠️ 未配置目标群号，插件将无法发送图片")
            logger.warning("请在 WebUI 中配置 target_group 参数")

        if not os.path.exists(self.image_folder):
            logger.warning(f"⚠️ 图片文件夹不存在: {self.image_folder}")
            logger.warning("请创建该文件夹并放入图片文件")

        if self.min_interval > self.max_interval:
            logger.error(f"❌ 最小间隔({self.min_interval})不能大于最大间隔({self.max_interval})")
            self.min_interval, self.max_interval = 18000, 36000

    def _auto_start(self) -> None:
        """插件启动时自动开始任务"""
        if self.target_group and os.path.exists(self.image_folder):
            self._start_background_task()
            logger.info("✅ 随机图片发送插件已自动启动")
        else:
            logger.info("⏸️  配置不完整，插件已暂停。请配置后使用 /开始发图 指令启动")

    def _start_background_task(self) -> None:
        """启动后台发送任务"""
        if self._background_task and not self._background_task.done():
            logger.warning("后台任务已在运行中")
            return

        self._is_running = True
        self._background_task = asyncio.create_task(self._send_loop())
        logger.info("🚀 后台发送任务已启动")

    async def _stop_background_task(self) -> None:
        """停止后台发送任务"""
        if not self._is_running:
            return

        self._is_running = False

        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                logger.info("🛑 后台任务已取消")

        logger.info(f"📊 任务停止 | 已发送: {self._sent_count} 张 | 错误: {self._error_count} 次")

    def _get_random_image_path(self) -> Optional[str]:
        """
        从图片文件夹中随机选择一张图片
        返回: 图片的绝对路径，如果没有可用图片则返回 None
        """
        folder_path = Path(self.image_folder)

        # 检查文件夹是否存在
        if not folder_path.exists():
            logger.error(f"❌ 图片文件夹不存在: {self.image_folder}")
            return None

        if not folder_path.is_dir():
            logger.error(f"❌ 路径不是文件夹: {self.image_folder}")
            return None

        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

        image_files = [
            file for file in folder_path.iterdir()
            if file.is_file() and file.suffix.lower() in image_extensions
        ]

        if not image_files:
            logger.warning(f"⚠️ 文件夹中没有找到图片文件: {self.image_folder}")
            return None

        selected = random.choice(image_files)
        return str(selected.absolute())

    async def _send_image(self, image_path: str) -> bool:
        """
        向目标群聊发送图片
        参数: image_path - 图片文件路径
        返回: 发送是否成功
        """
        if not self.target_group:
            logger.error("❌ 未配置目标群号")
            return False

        try:
            # 获取平台适配器
            platform = self.context.get_platform(PlatformAdapterType.AIOCQHTTP)

            if not platform or not hasattr(platform, 'get_client'):
                logger.error("❌ 无法获取 AIOCQHTTP 平台客户端")
                return False

            client = platform.get_client()

            abs_path = os.path.abspath(image_path)
            if os.name == 'nt':
                abs_path = abs_path.replace('\\', '/')
            file_uri = f"file:///{abs_path}"

            message = [{
                "type": "image",
                "data": {
                    "file": file_uri
                }
            }]

            # 调用 send_group_msg API
            result = await client.api.call_action('send_group_msg', **{
                'group_id': int(self.target_group),
                'message': message
            })

            if result and result.get('message_id'):
                self._sent_count += 1
                filename = os.path.basename(image_path)
                if self.verbose_logging:
                    logger.info(f"✅ 已发送图片 [{filename}] 到群 {self.target_group}")
                else:
                    logger.debug(f"已发送: {filename}")
                return True
            else:
                self._error_count += 1
                logger.warning(f"❌ API返回异常: {result}")
                return False

        except Exception as e:
            self._error_count += 1
            logger.error(f"❌ 发送图片失败: {e}")
            logger.error(f"   图片路径: {image_path}")
            logger.error(f"   目标群号: {self.target_group}")
            return False

    async def _send_loop(self) -> None:
        """
        主循环：无限循环发送图片
        每次循环：
        1. 随机选择一张图片
        2. 发送到目标群聊
        3. 等待随机时间间隔
        """
        logger.info("=" * 50)
        logger.info("🎲 随机图片发送任务已启动")
        logger.info(f"   图片文件夹: {self.image_folder}")
        logger.info(f"   目标群号: {self.target_group}")
        logger.info(f"   发送间隔: {self.min_interval} ~ {self.max_interval} 秒")
        logger.info("=" * 50)

        while self._is_running:
            try:
                image_path = self._get_random_image_path()

                if image_path:
                    success = await self._send_image(image_path)

                    if not success:
                        logger.warning("⚠️ 图片发送失败，将在下一个周期重试")
                else:
                    logger.warning("⚠️ 未找到可用图片，等待下一个周期")

                wait_time = random.uniform(self.min_interval, self.max_interval)

                minutes = int(wait_time // 60)
                seconds = int(wait_time % 60)
                logger.info(f"⏰ 下次发送将在 {minutes}分{seconds}秒 后 ({wait_time:.1f}秒)")

                await asyncio.sleep(wait_time)

            except asyncio.CancelledError:
                logger.info("🛑 任务被取消")
                break

            except Exception as e:
                self._error_count += 1
                logger.error(f"❌ 循环中出现意外错误: {e}", exc_info=True)
                logger.warning("⏳ 10秒后重试...")
                await asyncio.sleep(10)

    # ==================== 管理指令 ====================

    @command("random_image_start", alias={"开始发图", "启动发图"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_start(self, event: AstrMessageEvent) -> MessageEventResult:
        """手动启动随机图片发送任务"""
        if self._is_running:
            return MessageEventResult().message("⚠️ 任务已在运行中")

        self._validate_config()

        if not self.target_group:
            return MessageEventResult().message(
                "❌ 未配置目标群号\n"
                "请在 WebUI 中配置 target_group 参数"
            )

        if not os.path.exists(self.image_folder):
            return MessageEventResult().message(
                f"❌ 图片文件夹不存在: {self.image_folder}\n"
                "请创建该文件夹并放入图片文件"
            )

        self._start_background_task()
        return MessageEventResult().message(
            "✅ 随机图片发送任务已启动\n"
            f"📁 图片文件夹: {self.image_folder}\n"
            f"👥 目标群号: {self.target_group}\n"
            f"⏱️  发送间隔: {self.min_interval}~{self.max_interval}秒"
        )

    @command("random_image_stop", alias={"停止发图", "关闭发图"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_stop(self, event: AstrMessageEvent) -> MessageEventResult:
        """手动停止随机图片发送任务"""
        if not self._is_running:
            return MessageEventResult().message("⚠️ 任务未在运行")

        await self._stop_background_task()
        return MessageEventResult().message(
            "🛑 随机图片发送任务已停止\n"
            f"📊 统计: 已发送 {self._sent_count} 张，错误 {self._error_count} 次"
        )

    @command("random_image_status", alias={"发图状态", "查看状态"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_status(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看当前任务状态和统计信息"""
        status_text = "🟢 运行中" if self._is_running else "🔴 已停止"

        # 检查图片数量
        image_count = 0
        if os.path.exists(self.image_folder):
            folder = Path(self.image_folder)
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
            image_count = len([
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in image_extensions
            ])

        status_msg = (
            f"📊 随机图片发送状态\n"
            f"━━━━━━━━━━━━━━━\n"
            f"状态: {status_text}\n"
            f"📁 图片文件夹: {self.image_folder}\n"
            f"🖼️  可用图片: {image_count} 张\n"
            f"👥 目标群号: {self.target_group or '未配置'}\n"
            f"⏱️  发送间隔: {self.min_interval}~{self.max_interval}秒\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📈 已发送: {self._sent_count} 张\n"
            f"❌ 错误数: {self._error_count} 次"
        )

        return MessageEventResult().message(status_msg)

    @command("random_image_send", alias={"立即发图", "发一张"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_send_now(self, event: AstrMessageEvent) -> MessageEventResult:
        """立即发送一张随机图片（测试用）"""
        image_path = self._get_random_image_path()

        if not image_path:
            return MessageEventResult().message("❌ 未找到可用图片")

        success = await self._send_image(image_path)

        if success:
            filename = os.path.basename(image_path)
            return MessageEventResult().message(f"✅ 图片已发送\n📄 {filename}")
        else:
            return MessageEventResult().message("❌ 发送失败")

    @command("random_image_config", alias={"发图配置", "查看配置"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_config(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看当前配置信息"""
        config_msg = (
            f"⚙️ 随机图片发送配置\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📁 图片文件夹: {self.image_folder}\n"
            f"⏱️  最小间隔: {self.min_interval} 秒\n"
            f"⏱️  最大间隔: {self.max_interval} 秒\n"
            f"👥 目标群号: {self.target_group or '未配置'}\n"
            f"📝 详细日志: {'开启' if self.verbose_logging else '关闭'}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 修改配置请在 WebUI 中进行"
        )

        return MessageEventResult().message(config_msg)

    @command("random_image_reset", alias={"重置统计", "清空统计"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_reset_stats(self, event: AstrMessageEvent) -> MessageEventResult:
        """重置统计数据"""
        old_sent = self._sent_count
        old_error = self._error_count

        self._sent_count = 0
        self._error_count = 0

        return MessageEventResult().message(
            "🔄 统计数据已重置\n"
            f"原发送数: {old_sent} 张\n"
            f"原错误数: {old_error} 次"
        )

    # ==================== 生命周期管理 ====================

    async def terminate(self) -> None:
        """插件卸载时清理资源"""
        logger.info("🔄 正在关闭随机图片发送插件...")
        await self._stop_background_task()
        logger.info("✅ 插件已安全卸载")
