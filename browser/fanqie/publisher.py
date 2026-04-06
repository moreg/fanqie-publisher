import asyncio
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

from config import (
    FANQIE_BASE_URL, PAGE_LOAD_TIMEOUT,
    ERRORS_DIR
)
from browser.fanqie.selectors import ChapterManagePage, ChapterEditor, PublishDialog, Common
from browser.fanqie.exceptions import (
    PublishFailedException, SessionExpiredException,
    SelectorNotFoundException
)
from utils.logger import logger


@dataclass
class PublishResult:
    """发布结果"""
    success: bool
    chapter_title: str
    message: str
    already_exists: bool = False  # 章节是否已存在于番茄网站
    fanqie_chapter_id: Optional[str] = None
    screenshot_path: Optional[str] = None
    duration_ms: int = 0


class AsyncChapterPublisher:
    """番茄小说章节发布器 - 异步版本"""

    def __init__(self, page: Page):
        self.page = page

    async def check_chapter_exists(self, fanqie_book_id: str, chapter_title: str) -> tuple[bool, Optional[str]]:
        """检查章节是否已存在于番茄网站

        Returns:
            (exists, fanqie_chapter_id) - 是否存在，番茄章节ID
        """
        try:
            # 导航到章节管理页
            await self._goto_book_chapters(fanqie_book_id)
            await asyncio.sleep(2)

            # 尝试查找章节列表中的标题
            # 方法1: 通过 JavaScript 获取所有章节项
            chapters = await self.page.evaluate("""
                () => {
                    const results = [];
                    // 尝试多种选择器找到章节列表
                    const selectors = [
                        '.chapter-item',
                        '[class*="chapter-item"]',
                        '[class*="chapter-list"] tr',
                        '.chapter-table tr',
                        'tr[class*="chapter"]',
                        '[class*="chapter-content"] > div'
                    ];

                    let items = [];
                    for (const sel of selectors) {
                        items = document.querySelectorAll(sel);
                        if (items.length > 0) break;
                    }

                    items.forEach((item, index) => {
                        const text = item.textContent || '';
                        // 尝试提取标题
                        const titleSel = '[class*="title"], .title, [class*="name"]';
                        const titleEl = item.querySelector(titleSel);
                        const title = titleEl ? titleEl.textContent.trim() : text.substring(0, 50);

                        // 尝试提取状态
                        const statusSel = '[class*="status"], [class*="audit"], [class*="state"]';
                        const statusEl = item.querySelector(statusSel);
                        const status = statusEl ? statusEl.textContent.trim() : '';

                        results.push({
                            index: index,
                            title: title,
                            status: status,
                            fullText: text.substring(0, 200)
                        });
                    });

                    return results;
                }
            """)

            logger.info(f"在番茄网站上找到 {len(chapters)} 个章节")

            # 简化标题用于匹配（去除"第X章"等前缀）
            def normalize_title(title: str) -> str:
                import re
                # 去除"第X章"前缀
                title = re.sub(r'^第[零〇一二三四五六七八九十百千0-9]+[章节\s]+', '', title)
                return title.strip().lower()

            normalized_input = normalize_title(chapter_title)

            for ch in chapters:
                # 检查标题是否匹配
                normalized_ch_title = normalize_title(ch['title'])
                if normalized_input in normalized_ch_title or normalized_ch_title in normalized_input:
                    logger.info(f"找到匹配的章节: '{ch['title']}' (状态: {ch['status']})")
                    return True, ch['fullText'][:50]  # 返回章节标识

            logger.info(f"未找到章节 '{chapter_title}'")
            return False, None

        except Exception as e:
            logger.error(f"检查章节是否存在失败: {e}")
            return False, None

    async def publish_chapter(
        self,
        fanqie_book_id: str,
        chapter_title: str,
        chapter_content: str,
        publish_mode: str = "immediate",
        check_first: bool = True,
        timeout_seconds: int = 120
    ) -> PublishResult:
        """发布一个章节到番茄小说（异步）

        Args:
            fanqie_book_id: 番茄书籍ID
            chapter_title: 章节标题
            chapter_content: 章节内容
            publish_mode: 发布模式 (immediate/scheduled)
            check_first: 是否先检查章节是否已存在
            timeout_seconds: 发布超时时间，默认120秒
        """
        start_time = time.time()

        async def _do_publish():
            """实际发布逻辑"""
            # 1. 检查章节是否已存在
            if check_first:
                exists, chapter_id = await self.check_chapter_exists(fanqie_book_id, chapter_title)
                if exists:
                    duration = int((time.time() - start_time) * 1000)
                    logger.info(f"章节 '{chapter_title}' 已在番茄网站上存在，标记为已发布")
                    return PublishResult(
                        success=True,
                        chapter_title=chapter_title,
                        message="章节已存在，跳过发布",
                        already_exists=True,
                        fanqie_chapter_id=chapter_id,
                        duration_ms=duration,
                    )

            # 2. 导航到章节管理页
            await self._goto_book_chapters(fanqie_book_id)
            await asyncio.sleep(3)

            # 2.5 关闭可能存在的教程弹窗
            await self._close_all_popups()

            # 3. 导航到发布确认页面
            logger.info(">>> 步骤3: 进入发布确认页面...")

            # 先关闭弹窗
            await self._close_all_popups()
            await asyncio.sleep(1)

            # 点击新建章节按钮
            logger.info(">>> 点击新建章节按钮...")
            try:
                # 方案1: 直接点击按钮
                click_result = await self.page.evaluate("""
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const newChapterBtn = buttons.find(b =>
                            (b.textContent || '').includes('新建章节')
                        );
                        if (newChapterBtn) {
                            newChapterBtn.click();
                            return { success: true, text: newChapterBtn.textContent.trim() };
                        }
                        return { success: false, reason: 'button not found' };
                    }
                """)
                if click_result and click_result.get('success'):
                    logger.info(f"点击新建章节按钮成功")
                else:
                    logger.warning(f"点击新建章节按钮失败: {click_result}")
                    return

                # 等待弹窗出现
                logger.info(">>> 等待新建章节弹窗...")
                await asyncio.sleep(3)

                # 检查是否出现了"上传文档"弹窗
                dialog_check = await self.page.evaluate("""
                    () => {
                        // 查找包含"上传文档"或"手动输入"的元素
                        const buttons = Array.from(document.querySelectorAll('button'));
                        for (const btn of buttons) {
                            const text = btn.textContent || '';
                            if (text.includes('手动输入')) {
                                return { success: true, found: 'manual-input', text: text.trim() };
                            }
                        }
                        // 检查页面文本
                        const allText = document.body.innerText;
                        if (allText.includes('上传文档')) {
                            return { success: true, found: 'upload' };
                        }
                        return { success: false };
                    }
                """)
                logger.info(f">>> 弹窗检查: {dialog_check}")

                # 如果出现"上传文档"弹窗，点击"手动输入"
                if dialog_check and dialog_check.get('success') and dialog_check.get('found') in ['upload', 'manual-input']:
                    logger.info(">>> 出现上传文档弹窗，点击'手动输入'...")
                    manual_btn_click = await self.page.evaluate("""
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button'));
                            for (const btn of buttons) {
                                const text = btn.textContent || '';
                                if (text.includes('手动输入')) {
                                    btn.click();
                                    return { success: true, text: text.trim() };
                                }
                            }
                            return { success: false };
                        }
                    """)
                    logger.info(f">>> 点击手动输入结果: {manual_btn_click}")
                    await asyncio.sleep(3)

                # 等待编辑抽屉/界面出现
                logger.info(">>> 等待编辑界面出现...")
                for i in range(10):
                    drawer_check = await self.page.evaluate("""
                        () => {
                            // 查找抽屉中的标题输入框
                            const inputs = document.querySelectorAll('input');
                            for (const inp of inputs) {
                                const placeholder = (inp.placeholder || '').toLowerCase();
                                if (placeholder.includes('标题') || placeholder.includes('chapter')) {
                                    const rect = inp.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        return { success: true, found: 'title-input', placeholder: inp.placeholder };
                                    }
                                }
                            }
                            return { success: false };
                        }
                    """)
                    if drawer_check and drawer_check.get('success'):
                        logger.info(f">>> 编辑界面已出现: {drawer_check}")
                        break
                    await asyncio.sleep(1)

                logger.info(">>> 开始填写发布内容...")

            except Exception as e:
                logger.error(f"点击新建章节按钮失败: {e}")
                raise

            # 检查是否被重定向到登录页
            if "login" in self.page.url.lower():
                raise SessionExpiredException("Session已过期，需要重新登录")

            # 等待编辑界面完全加载
            await asyncio.sleep(2)

            # 4a. 填写标题（在抽屉内的编辑界面）
            logger.info(">>> 步骤4: 填写章节标题...")
            await self._fill_title_on_confirm_page(chapter_title)

            # 4b. 点击"添加正文"按钮（如果存在）
            logger.info(">>> 步骤4b: 点击添加正文按钮...")
            try:
                add_btn = await self.page.wait_for_selector("button:has-text('添加正文')", timeout=3000)
                if add_btn and await add_btn.is_visible():
                    await add_btn.click()
                    await asyncio.sleep(2)
                    logger.info("已点击添加正文按钮")
            except Exception as e:
                logger.debug(f"点击添加正文按钮失败（可能不需要）: {e}")

            # 4c. 填写正文
            logger.info(">>> 步骤5: 填写章节正文...")
            await self._fill_content_on_confirm_page(chapter_content)

            # 4d. 点击确认发布
            logger.info(">>> 步骤6: 点击确认发布...")
            await self._click_confirm_publish()
            await asyncio.sleep(2)

            # 4e. 处理确认弹窗
            logger.info(">>> 步骤7: 处理确认弹窗...")
            await self._handle_confirm_dialog()

            duration = int((time.time() - start_time) * 1000)
            logger.info(f">>> 章节 '{chapter_title}' 发布成功，耗时 {duration}ms")

            return PublishResult(
                success=True,
                chapter_title=chapter_title,
                message="发布成功",
                duration_ms=duration,
            )

        try:
            # 使用 asyncio.wait_for 实现真正的超时取消
            result = await asyncio.wait_for(
                _do_publish(),
                timeout=timeout_seconds
            )
            return result

        except asyncio.TimeoutError:
            duration = int((time.time() - start_time) * 1000)
            await self._save_error_screenshot(f"{chapter_title}_timeout")
            logger.error(f"发布章节 '{chapter_title}' 超时 ({timeout_seconds}秒)")
            return PublishResult(
                success=False,
                chapter_title=chapter_title,
                message=f"发布超时 ({timeout_seconds}秒)",
                duration_ms=duration,
            )
        except SessionExpiredException:
            raise
        except Exception as e:
            duration = int((time.time() - start_time) * 1000)
            screenshot_path = await self._save_error_screenshot(chapter_title)
            logger.error(f"发布章节 '{chapter_title}' 失败: {e}")
            return PublishResult(
                success=False,
                chapter_title=chapter_title,
                message=str(e),
                screenshot_path=screenshot_path,
                duration_ms=duration,
            )

    async def _goto_book_chapters(self, fanqie_book_id: str):
        """导航到书籍章节管理页"""
        url = f"{FANQIE_BASE_URL}/main/writer/chapter-manage/{fanqie_book_id}"
        logger.info(f"导航到 {url}")
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 检查是否被重定向到登录页
        if "login" in self.page.url.lower():
            raise SessionExpiredException("Session已过期，需要重新登录")

        # 检查页面是否显示错误
        page_text = await self.page.text_content("body") or ""
        if "抱歉" in page_text or "不存在" in page_text:
            raise PublishFailedException("页面不存在，可能URL错误或Cookie已过期")

    async def _click_new_chapter(self):
        """点击新建章节按钮"""
        selectors = ChapterManagePage.NEW_CHAPTER_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    
                    await el.click()
                    logger.info("已点击新建章节按钮")
                    
                    # 等待更长时间让抽屉打开
                    await asyncio.sleep(10)
                    
                    await self._wait_for_editor_popup()
                    return
            except Exception as e:
                logger.debug(f"选择器 {selector} 失败: {e}")
                continue
        raise SelectorNotFoundException("找不到新建章节按钮")

    async def _check_drawer_opened(self) -> bool:
        """检查抽屉是否已打开"""
        try:
            # 检查页面上是否有输入框出现
            inputs = await self.page.query_selector_all("input")
            for inp in inputs:
                try:
                    if await inp.is_visible():
                        placeholder = await inp.get_attribute("placeholder") or ""
                        if "标题" in placeholder or "章节" in placeholder:
                            logger.info("检测到抽屉中的标题输入框")
                            return True
                except:
                    pass

            # 检查是否有抽屉相关的元素
            drawer_elements = await self.page.query_selector_all(
                "[class*='drawer'], [class*='Drawer'], .arco-drawer, [role='dialog']"
            )
            for el in drawer_elements:
                try:
                    if await el.is_visible():
                        return True
                except:
                    pass

            return False
        except Exception as e:
            logger.debug(f"检查抽屉状态失败: {e}")
            return False

    async def _click_new_chapter_js(self):
        """使用JavaScript点击新建章节按钮"""
        try:
            result = await self.page.evaluate("""
                () => {
                    // 查找所有包含"新建章节"文本的按钮
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent || '';
                        if (text.includes('新建章节') || text.includes('新建') || text.includes('创建章节')) {
                            btn.click();
                            return { success: true, text: text.trim() };
                        }
                    }

                    // 尝试查找arco-btn
                    const arcoBtns = document.querySelectorAll('.arco-btn-primary');
                    for (const btn of arcoBtns) {
                        const text = btn.textContent || '';
                        if (text.includes('新') || text.includes('创建')) {
                            btn.click();
                            return { success: true, text: text.trim() };
                        }
                    }

                    return { success: false };
                }
            """)
            if result and result.get('success'):
                logger.info(f"JavaScript点击成功: {result.get('text')}")
            else:
                logger.warning("JavaScript点击未找到按钮")
        except Exception as e:
            logger.debug(f"JavaScript点击失败: {e}")

    async def _wait_for_editor_popup(self):
        """等待编辑器弹窗/抽屉出现"""
        popup_selectors = [
            "[class*='drawer']",
            "[class*='Drawer']",
            "[class*='slide-over']",
            "[class*='slideOver']",
            "[class*='side-panel']",
            "[class*='sidePanel']",
            "[class*='panel'][class*='right']",
            "[class*='editor-container']",
            "[class*='EditorContainer']",
            "[class*='chapter-editor']",
            "[class*='ChapterEditor']",
            "dialog",
            ".arco-modal",
            ".arco-drawer",
            ".arco-dialog",
            "[role='dialog']",
            "[class*='modal']",
            "[class*='Modal']",
            "[class*='popup']",
            "[class*='dialog']",
            "[class*='Dialog']",
        ]
        
        max_attempts = 20
        for attempt in range(max_attempts):
            for selector in popup_selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el and await el.is_visible():
                        logger.info(f"检测到弹窗/抽屉已出现 (选择器: {selector})")
                        await asyncio.sleep(1)
                        return
                except Exception:
                    continue
            
            inputs = await self.page.query_selector_all("input")
            visible_inputs = []
            for inp in inputs:
                try:
                    if await inp.is_visible():
                        visible_inputs.append(inp)
                except Exception:
                    pass
            
            if visible_inputs:
                logger.info(f"检测到 {len(visible_inputs)} 个可见输入框，编辑器已加载")
                await asyncio.sleep(0.5)
                return
            
            await asyncio.sleep(0.5)
        
        await self._save_debug_screenshot("popup_not_detected")
        logger.warning("未检测到弹窗，继续尝试其他方法")

    async def _close_tutorial_popup(self):
        """关闭教程弹窗（可能有多个）"""
        from browser.fanqie.selectors import Common

        # 最多尝试关闭5次教程弹窗
        for attempt in range(5):
            selectors = Common.TUTORIAL_CLOSE.split(", ")
            found = False
            for selector in selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=2000)
                    if el and await el.is_visible():
                        await el.click()
                        logger.info(f"已关闭教程弹窗 (第{attempt + 1}次)")
                        found = True
                        await asyncio.sleep(0.5)  # 等待动画
                        break
                except Exception:
                    continue

            if not found:
                if attempt == 0:
                    logger.debug("未发现教程弹窗")
                break

        return True

    async def _close_all_popups(self):
        """关闭所有弹窗（教程弹窗等）"""
        from browser.fanqie.selectors import Common

        # 最多尝试关闭10次弹窗
        for attempt in range(10):
            # 先保存截图看看弹窗内容
            await self._save_debug_screenshot(f"popup_before_close_{attempt + 1}")

            selectors = Common.TUTORIAL_CLOSE.split(", ")
            found = False
            for selector in selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=2000)
                    if el and await el.is_visible():
                        btn_text = await el.text_content()
                        btn_class = await el.get_attribute("class") or ""
                        btn_style = await el.get_attribute("style") or ""

                        # 跳过序号输入框的清除按钮（serial-icon）
                        if 'serial-icon' in btn_class:
                            logger.debug(f"跳过序号清除按钮")
                            continue

                        # 跳过箭头按钮
                        if 'arrow' in btn_class.lower():
                            logger.debug(f"跳过箭头按钮")
                            continue

                        logger.info(f"发现弹窗按钮: text='{btn_text}', class='{btn_class[:50]}'")
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.2)
                        await el.click()
                        logger.info(f"已关闭弹窗 (第{attempt + 1}次)")
                        found = True
                        await asyncio.sleep(1.5)  # 等待动画完成
                        break
                except Exception as e:
                    logger.debug(f"选择器 {selector} 失败: {e}")
                    continue

            if not found:
                # 如果没有找到关闭按钮，尝试检查是否是序号弹窗
                serial_check = await self.page.evaluate("""
                    () => {
                        // 检查页面上是否有"序号"相关的弹窗
                        const bodyText = document.body.innerText;
                        if (bodyText.includes('序号') && bodyText.includes('请输入')) {
                            // 查找关闭按钮（通常是×或者包含close的）
                            const closeBtn = Array.from(document.querySelectorAll('button, [role="button"], span, div')).find(el => {
                                const cls = el.className || '';
                                const text = el.textContent || '';
                                const style = el.getAttribute('style') || '';
                                // 查找可能是关闭按钮的元素
                                return (text.trim() === '×' || text.trim() === '×' || cls.includes('close') || cls.includes('Close')) &&
                                       !cls.includes('serial-icon');
                            });
                            if (closeBtn) {
                                return { found: true, type: 'serial-popup', closeBtn: closeBtn.textContent };
                            }
                            return { found: true, type: 'serial-popup', closeBtn: null };
                        }
                        return { found: false };
                    }
                """)
                if serial_check and serial_check.get('found'):
                    logger.info(f"检测到序号弹窗: {serial_check}")
                    # 尝试点击关闭按钮
                    close_result = await self.page.evaluate("""
                        () => {
                            // 查找所有可能的关闭按钮
                            const elements = document.querySelectorAll('button, [role="button"]');
                            for (const el of elements) {
                                const cls = el.className || '';
                                const text = el.textContent || '';
                                // 跳过序号相关按钮
                                if (cls.includes('serial-icon') || cls.includes('serial')) continue;
                                // 跳过箭头按钮
                                if (text.includes('←') || text.includes('→') || text.includes('arrow')) continue;
                                // 查找关闭按钮
                                if (text.trim() === '×' || cls.includes('close') || cls.includes('Close')) {
                                    el.click();
                                    return { success: true, text: text.trim() };
                                }
                            }
                            return { success: false };
                        }
                    """)
                    if close_result and close_result.get('success'):
                        logger.info(f"已关闭序号弹窗: {close_result}")
                        await asyncio.sleep(1.5)
                        found = True

            if not found:
                break

        # 按ESC键来关闭弹窗
        logger.info("尝试按ESC键关闭弹窗...")
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            logger.info("已按ESC键关闭弹窗")
        except Exception as e:
            logger.debug(f"按ESC键失败: {e}")

        return True

    async def _handle_confirm_dialog(self):
        """处理发布确认弹窗流程

        完整流程：
        1. "检测到你还有错别字未修改" -> 点击"提交"
        2. "是否进行内容风险检测？" -> 点击"确定"
        3. "发布设置"弹窗 -> AI单选框选"否" -> 点击"确认发布"
        4. 等待页面跳转和"已提交"吐司
        """
        logger.info(">>> 开始处理发布确认流程...")

        # 处理多层弹窗，最多尝试10轮
        max_retries = 10
        for retry in range(max_retries):
            await asyncio.sleep(1.5)

            # 截图以便调试
            await self._save_debug_screenshot(f"confirm_dialog_retry_{retry}")

            # ===== 弹窗1 & 2: 错别字提示 & 风险检测 =====
            # 尝试点击任何确认/提交按钮
            submit_selectors = [
                "button:has-text('提交')",
                "button:has-text('确定')",
                "button:has-text('确认')",
            ]

            for selector in submit_selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=500)
                    if el:
                        btn_text = await el.text_content()
                        is_visible = await el.is_visible()
                        btn_class = await el.get_attribute("class") or ""

                        # 跳过取消按钮
                        if '取消' in (btn_text or ''):
                            continue

                        # 跳过关闭按钮
                        if '关闭' in (btn_text or '') and 'arco-btn-secondary' in btn_class:
                            continue

                        if is_visible:
                            logger.info(f"点击按钮: '{btn_text.strip()}'")
                            await el.click()
                            await asyncio.sleep(1)
                            break
                except:
                    pass

            # ===== 弹窗3: 发布设置（AI选择） =====
            # 查找并选择"否"（不使用AI）
            ai_selectors = [
                "button:has-text('否')",
                "button:has-text('不是')",
                "[class*='radio']:has-text('否')",
                "[class*='radio']:has-text('不使用')",
            ]

            for selector in ai_selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=500)
                    if el:
                        btn_text = await el.text_content()
                        is_visible = await el.is_visible()
                        if is_visible:
                            logger.info(f"选择AI选项: '{btn_text.strip()}'")
                            await el.click()
                            await asyncio.sleep(0.5)
                            break
                except:
                    pass

            # 点击"确认发布"按钮
            publish_selectors = [
                "button:has-text('确认发布')",
                "button:has-text('发布')",
                "button:has-text('确认')",
                ".arco-btn-primary:has-text('发布')",
                ".arco-btn-primary:has-text('确认')",
                ".arco-modal button:has-text('确认发布')",
                ".arco-modal button:has-text('发布')",
            ]

            for selector in publish_selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=500)
                    if el:
                        btn_text = await el.text_content()
                        is_visible = await el.is_visible()
                        btn_class = await el.get_attribute("class") or ""

                        # 跳过取消按钮
                        if '取消' in (btn_text or ''):
                            continue

                        if is_visible:
                            logger.info(f"点击发布确认: '{btn_text.strip()}'")
                            await el.click()
                            await asyncio.sleep(2)

                            # 检查是否跳转到新页面（发布成功的标志）
                            try:
                                await self.page.wait_for_url("**/chapter-manage**", timeout=5000)
                                logger.info("检测到页面跳转成功，可能发布完成")
                            except:
                                pass

                            # 检查是否有"已提交"相关的吐司
                            try:
                                toast = await self.page.wait_for_selector("[class*='toast']", timeout=3000)
                                toast_text = await toast.text_content() if toast else ""
                                if toast_text and '提交' in toast_text:
                                    logger.info(f"检测到成功吐司: {toast_text}")
                                    return True
                            except:
                                pass

                            return True
                except:
                    pass

        # 最终回退：JavaScript处理
        logger.info("使用JavaScript最终处理...")
        await self.page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));

                // 1. 先点击任何非取消的确认按钮
                for (const btn of buttons) {
                    const text = (btn.textContent || '').trim();
                    if (text.includes('提交') || text.includes('确定') || text.includes('确认')) {
                        if (!text.includes('取消')) {
                            btn.click();
                            break;
                        }
                    }
                }
            }
        """)
        await asyncio.sleep(2)

        logger.info("发布确认流程执行完成")
        return True

    async def _fill_title(self, title: str):
        """填写章节标题"""
        await self._save_debug_screenshot("before_fill_title")

        # 先等待抽屉完全加载
        await asyncio.sleep(3)

        # 使用Playwright的locator API查找标题输入框
        # Playwright的locator比querySelector更可靠
        logger.info("尝试使用Playwright locator查找标题输入框...")

        # 方法1: 使用get_by_placeholder
        try:
            locator = self.page.get_by_placeholder("请输入章节标题")
            await locator.wait_for(timeout=5000)
            if await locator.is_visible():
                await locator.click()
                await asyncio.sleep(0.3)
                await locator.fill(title)
                logger.info("已填写标题 (方法1: get_by_placeholder)")
                await self._save_debug_screenshot("after_fill_title")
                return
        except Exception as e:
            logger.debug(f"方法1失败: {e}")

        # 方法2: 使用get_by_role
        try:
            locator = self.page.get_by_role("textbox", name="章节标题")
            await locator.wait_for(timeout=5000)
            if await locator.is_visible():
                await locator.click()
                await asyncio.sleep(0.3)
                await locator.fill(title)
                logger.info("已填写标题 (方法2: get_by_role)")
                await self._save_debug_screenshot("after_fill_title")
                return
        except Exception as e:
            logger.debug(f"方法2失败: {e}")

        # 方法3: 查找所有输入框并逐个检查
        try:
            inputs = self.page.locator("input")
            count = await inputs.count()
            logger.info(f"找到 {count} 个input元素")

            for i in range(count):
                el = inputs.nth(i)
                try:
                    visible = await el.is_visible()
                    if not visible:
                        continue

                    placeholder = await el.get_attribute("placeholder") or ""
                    cls = await el.get_attribute("class") or ""

                    logger.info(f"检查input[{i}]: placeholder='{placeholder}', class='{cls[:40]}'")

                    # 如果placeholder包含"标题"或"章节"或"请输入"
                    if any(keyword in placeholder for keyword in ["标题", "章节", "请输入"]):
                        await el.scroll_into_view_if_needed()
                        await el.click()
                        await asyncio.sleep(0.3)
                        await el.fill(title)
                        logger.info(f"已填写标题 (方法3: input[{i}])")
                        await self._save_debug_screenshot("after_fill_title")
                        return
                except Exception as e:
                    logger.debug(f"input[{i}] 失败: {e}")
                    continue
        except Exception as e:
            logger.debug(f"方法3失败: {e}")

        # 方法4: 使用JavaScript查找并操作
        try:
            js_result = await self.page.evaluate("""
                (title) => {
                    // 查找所有有placeholder的input
                    const inputs = document.querySelectorAll('input');
                    for (let i = 0; i < inputs.length; i++) {
                        const inp = inputs[i];
                        const placeholder = inp.placeholder || '';
                        const rect = inp.getBoundingClientRect();

                        // 检查是否可见且placeholder匹配
                        if (rect.width > 0 && rect.height > 0 &&
                            (placeholder.includes('标题') ||
                             placeholder.includes('章节') ||
                             placeholder.includes('请输入'))) {

                            // 尝试多种方式填写
                            inp.focus();

                            // 清空
                            inp.select();
                            inp.value = '';

                            // 方法1: 直接设置value
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeInputValueSetter.call(inp, title);

                            // 触发事件
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            inp.dispatchEvent(new Event('blur', { bubbles: true }));

                            return {
                                success: true,
                                method: 'js_direct',
                                placeholder: placeholder,
                                index: i
                            };
                        }
                    }

                    // 尝试arco-input组件
                    const arcoInputs = document.querySelectorAll('[class*="arco-input"], .arco-input');
                    for (const wrapper of arcoInputs) {
                        const rect = wrapper.getBoundingClientRect();
                        if (rect.width > 0) {
                            const input = wrapper.querySelector('input');
                            if (input) {
                                const placeholder = input.placeholder || '';
                                if (placeholder.includes('标题') || placeholder.includes('章节')) {
                                    input.focus();
                                    input.select();
                                    input.value = title;
                                    input.dispatchEvent(new Event('input', { bubbles: true }));
                                    input.dispatchEvent(new Event('change', { bubbles: true }));
                                    return {
                                        success: true,
                                        method: 'arco-input',
                                        placeholder: placeholder
                                    };
                                }
                            }
                        }
                    }

                    // 打印所有可见input用于调试
                    const debug = [];
                    inputs.forEach((inp, idx) => {
                        const rect = inp.getBoundingClientRect();
                        debug.push({
                            index: idx,
                            placeholder: inp.placeholder || '',
                            className: inp.className || '',
                            rect: rect.width + 'x' + rect.height,
                            visible: rect.width > 0 && rect.height > 0
                        });
                    });

                    return { success: false, debug: debug };
                }
            """, title)

            if js_result and js_result.get('success'):
                logger.info(f"通过JavaScript填写标题成功: {js_result.get('method')}")
                await self._save_debug_screenshot("after_fill_title")
                return

            if js_result and js_result.get('debug'):
                logger.warning(f"页面上的input元素: {js_result['debug']}")
        except Exception as e:
            logger.debug(f"方法4失败: {e}")

        # 方法5: 尝试查找label关联的input
        try:
            locator = self.page.locator("label:has-text('章节标题')")
            count = await locator.count()
            if count > 0:
                # 找到label，尝试获取关联的input
                for i in range(count):
                    label = locator.nth(i)
                    try:
                        # 尝试点击label
                        input_in_label = label.locator("input")
                        if await input_in_label.count() > 0:
                            el = input_in_label.first
                            await el.fill(title)
                            logger.info("已填写标题 (方法5: label>input)")
                            await self._save_debug_screenshot("after_fill_title")
                            return
                    except:
                        pass

                    # 尝试通过for属性关联的input
                    for_attr = await label.get_attribute("for")
                    if for_attr:
                        input_el = self.page.locator(f"#{for_attr}")
                        if await input_el.count() > 0:
                            await input_el.first.fill(title)
                            logger.info("已填写标题 (方法5: label[for]>input)")
                            await self._save_debug_screenshot("after_fill_title")
                            return
            else:
                # 尝试任何包含"章节标题"文本的label
                all_labels = self.page.locator("label")
                for i in range(await all_labels.count()):
                    label = all_labels.nth(i)
                    try:
                        text = await label.inner_text()
                        if "章节标题" in text:
                            input_el = label.locator("input")
                            if await input_el.count() > 0:
                                await input_el.first.fill(title)
                                logger.info("已填写标题 (方法5: label with text)")
                                await self._save_debug_screenshot("after_fill_title")
                                return
                    except:
                        pass
        except Exception as e:
            logger.debug(f"方法5失败: {e}")

        await self._save_debug_screenshot("title_input_debug")
        raise SelectorNotFoundException("找不到标题输入框")

    async def _click_add_content(self):
        """点击"添加正文"按钮"""
        from browser.fanqie.selectors import ChapterEditor

        selectors = ChapterEditor.ADD_CONTENT_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    logger.info("已点击添加正文按钮")
                    return
            except Exception as e:
                logger.debug(f"点击添加正文按钮失败: {e}")
                continue
        # 如果没找到按钮，可能编辑器已经显示，直接返回
        logger.warning("未找到添加正文按钮，假设编辑器已显示")
        return

    async def _fill_content(self, content: str):
        """填写章节内容"""
        await self._save_debug_screenshot("before_fill_content")

        # 先等待编辑器加载
        await asyncio.sleep(2)

        # 方法1: 使用Playwright locator查找正文输入框
        logger.info("尝试使用Playwright locator查找正文输入框...")

        # 尝试通过placeholder查找
        try:
            locator = self.page.get_by_placeholder("请输入正文")
            await locator.wait_for(timeout=5000)
            if await locator.is_visible():
                await locator.click()
                await asyncio.sleep(0.3)
                await locator.fill(content)
                logger.info("已填写正文 (方法1: get_by_placeholder)")
                await self._save_debug_screenshot("after_fill_content")
                return
        except Exception as e:
            logger.debug(f"方法1失败: {e}")

        # 方法2: 查找所有textarea
        try:
            textareas = self.page.locator("textarea")
            count = await textareas.count()
            logger.info(f"找到 {count} 个textarea")

            for i in range(count):
                el = textareas.nth(i)
                try:
                    visible = await el.is_visible()
                    if not visible:
                        continue

                    placeholder = await el.get_attribute("placeholder") or ""
                    cls = await el.get_attribute("class") or ""
                    logger.info(f"textarea[{i}]: placeholder='{placeholder}', class='{cls[:40]}'")

                    await el.scroll_into_view_if_needed()
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.fill(content)
                    logger.info(f"已填写正文 (方法2: textarea[{i}])")
                    await self._save_debug_screenshot("after_fill_content")
                    return
                except Exception as e:
                    logger.debug(f"textarea[{i}] 失败: {e}")
                    continue
        except Exception as e:
            logger.debug(f"方法2失败: {e}")

        # 方法3: 查找contentEditable元素
        try:
            editors = self.page.locator("[contenteditable='true']")
            count = await editors.count()
            logger.info(f"找到 {count} 个contentEditable元素")

            for i in range(count):
                el = editors.nth(i)
                try:
                    visible = await el.is_visible()
                    if not visible:
                        continue

                    cls = await el.get_attribute("class") or ""
                    logger.info(f"contentEditable[{i}]: class='{cls[:40]}'")

                    await el.scroll_into_view_if_needed()
                    await el.click()
                    await asyncio.sleep(0.3)

                    # 使用键盘输入
                    await self.page.keyboard.press("Control+a")
                    await asyncio.sleep(0.1)
                    await self.page.keyboard.type(content, delay=10)
                    logger.info(f"已填写正文 (方法3: contentEditable[{i}])")
                    await self._save_debug_screenshot("after_fill_content")
                    return
                except Exception as e:
                    logger.debug(f"contentEditable[{i}] 失败: {e}")
                    continue
        except Exception as e:
            logger.debug(f"方法3失败: {e}")

        # 方法4: 使用JavaScript查找并填写
        try:
            js_result = await self.page.evaluate("""
                (content) => {
                    // 查找textarea
                    const textareas = document.querySelectorAll('textarea');
                    for (let i = 0; i < textareas.length; i++) {
                        const ta = textareas[i];
                        const rect = ta.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            ta.focus();
                            ta.select();
                            ta.value = content;
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                            ta.dispatchEvent(new Event('change', { bubbles: true }));
                            return { success: true, method: 'textarea', index: i };
                        }
                    }

                    // 查找contentEditable
                    const editors = document.querySelectorAll('[contenteditable="true"]');
                    for (let i = 0; i < editors.length; i++) {
                        const editor = editors[i];
                        const rect = editor.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            editor.focus();

                            // 清空内容
                            editor.innerHTML = '';

                            // 插入文本
                            const textNode = document.createTextNode(content);
                            editor.appendChild(textNode);

                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                            return { success: true, method: 'contenteditable', index: i };
                        }
                    }

                    // 查找富文本编辑器
                    const richEditors = document.querySelectorAll('.ql-editor, .ProseMirror');
                    for (const editor of richEditors) {
                        const rect = editor.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            editor.focus();
                            editor.innerHTML = '';
                            const textNode = document.createTextNode(content);
                            editor.appendChild(textNode);
                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                            return { success: true, method: 'rich-editor', class: editor.className };
                        }
                    }

                    // 打印调试信息
                    const debug = {
                        textareas: textareas.length,
                        editors: editors.length,
                        visible: []
                    };

                    document.querySelectorAll('textarea, [contenteditable]').forEach((el, i) => {
                        const rect = el.getBoundingClientRect();
                        debug.visible.push({
                            tag: el.tagName,
                            className: el.className || '',
                            rect: rect.width + 'x' + rect.height
                        });
                    });

                    return { success: false, debug: debug };
                }
            """, content)

            if js_result and js_result.get('success'):
                logger.info(f"通过JavaScript填写正文成功: {js_result.get('method')}")
                await self._save_debug_screenshot("after_fill_content")
                return

            if js_result and js_result.get('debug'):
                logger.warning(f"页面上的编辑器元素: {js_result['debug']}")
        except Exception as e:
            logger.debug(f"方法4失败: {e}")

        # 方法5: 查找包含"正文"文本的元素
        try:
            # 查找所有包含"正文"的label或span
            labels = self.page.locator("text=正文")
            count = await labels.count()
            logger.info(f"找到 {count} 个包含'正文'的元素")

            for i in range(count):
                label = labels.nth(i)
                try:
                    # 查找相邻的textarea
                    textarea = label.locator("xpath=following-sibling::textarea")
                    if await textarea.count() > 0:
                        await textarea.first.fill(content)
                        logger.info("已填写正文 (方法5: label+textarea)")
                        await self._save_debug_screenshot("after_fill_content")
                        return
                except:
                    pass
        except Exception as e:
            logger.debug(f"方法5失败: {e}")

        await self._save_debug_screenshot("content_fill_debug")
        raise SelectorNotFoundException("找不到正文输入框")

    async def _click_confirm(self):
        """点击确定/确认按钮"""
        from browser.fanqie.selectors import ChapterEditor

        selectors = ChapterEditor.CONFIRM_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el and await el.is_enabled():
                    await el.click()
                    logger.info(f"已点击确定按钮 (选择器: {selector})")
                    return
            except Exception as e:
                logger.debug(f"点击确定按钮失败: {e}")
                continue

        # 如果确定按钮没找到，尝试下一步按钮
        try:
            selectors = ChapterEditor.NEXT_BTN.split(", ")
            for selector in selectors:
                el = await self.page.wait_for_selector(selector, timeout=3000)
                if el and await el.is_enabled():
                    await el.click()
                    logger.info("已点击下一步按钮")
                    return
        except Exception:
            pass

        raise SelectorNotFoundException("找不到确定或下一步按钮")

    async def _click_publish_on_confirm_page(self):
        """在发布确认页面上点击发布按钮"""
        # 关闭可能存在的弹窗
        await self._close_all_popups()
        await asyncio.sleep(1)

        # 发布确认页面的按钮选择器
        publish_selectors = [
            "button:has-text('发布')",
            "button:has-text('确认发布')",
            "button:has-text('立即发布')",
            "button:has-text('提交')",
            "[class*='publish'] button",
            "button.btn-publish",
        ]

        for selector in publish_selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    logger.info(f"已点击发布按钮 (选择器: {selector})")
                    return
            except Exception as e:
                logger.debug(f"选择器 {selector} 失败: {e}")
                continue

        # 保存调试截图
        await self._save_debug_screenshot("publish_confirm_page")
        logger.warning("未找到发布确认按钮")

    async def _click_next(self):
        """点击下一步按钮"""
        selectors = ChapterEditor.NEXT_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el and await el.is_enabled():
                    await el.click()
                    logger.info("已点击下一步/发布按钮")
                    return
            except Exception:
                continue
        raise SelectorNotFoundException("找不到下一步按钮")

    async def _click_submit(self) -> bool:
        """点击提交审核按钮"""
        selectors = Common.SUBMIT_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el and await el.is_enabled():
                    await el.click()
                    logger.info("已点击提交审核按钮")
                    return True
            except Exception:
                continue
        logger.warning("未找到提交审核按钮")
        return False

    async def _select_publish_now(self) -> bool:
        """选择立即发布选项"""
        selectors = PublishDialog.PUBLISH_NOW.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    logger.info("已选择立即发布")
                    return True
            except Exception:
                continue
        logger.warning("未找到立即发布选项")
        return False

    async def _confirm_publish(self, publish_mode: str = "immediate"):
        """确认发布"""
        if publish_mode == "immediate":
            selectors = PublishDialog.PUBLISH_NOW.split(", ")
            for selector in selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=3000)
                    if el:
                        await el.click()
                        break
                except Exception:
                    continue

        await asyncio.sleep(1)
        selectors = PublishDialog.CONFIRM_BTN.split(", ")
        for selector in selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    logger.info("已点击确认发布按钮")
                    return
            except Exception:
                continue
        logger.warning("未找到确认按钮")

    async def _save_debug_screenshot(self, name: str) -> str:
        """保存调试截图"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_{name}_{timestamp}.png"
            filepath = str(ERRORS_DIR / filename)
            await self.page.screenshot(path=filepath)
            logger.info(f"已保存调试截图: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"保存调试截图失败: {e}")
            return ""

    async def _save_error_screenshot(self, chapter_title: str) -> str:
        """保存错误截图"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c for c in chapter_title if c.isalnum() or c in "_ -")[:30]
            filename = f"{timestamp}_{safe_title}.png"
            filepath = str(ERRORS_DIR / filename)
            await self.page.screenshot(path=filepath)
            logger.info(f"已保存错误截图: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"保存截图失败: {e}")
            return ""

    # ============ 发布确认页面处理方法 ============

    async def _fill_title_on_confirm_page(self, title: str):
        """在发布确认页面上填写章节序号和标题

        番茄小说编辑器有两个输入框：
        - 左侧：章节序号（如"第2章"）
        - 右侧：章节标题（不含序号部分）
        """
        await self._save_debug_screenshot("confirm_page_before_title")
        await asyncio.sleep(2)  # 等待页面完全加载

        # 从完整标题中提取章节序号数字和实际标题
        import re
        # 匹配"第X章"格式，X可以是中文数字或阿拉伯数字
        chapter_match = re.match(r'^第([零一二三四五六七八九十百千0-9]+)章\s*(.*)$', title)
        if chapter_match:
            chapter_number = chapter_match.group(1)  # 如"三"或"3"
            chapter_title_only = chapter_match.group(2)  # 如"测试标题"
        else:
            chapter_number = ""
            chapter_title_only = title

        logger.info(f">>> 解析标题: 完整='{title}', 序号='{chapter_number}', 标题='{chapter_title_only}'")

        # 填写序号数字
        if chapter_number:
            logger.info(f">>> 填写章节序号: '{chapter_number}'")
            
            fill_result = await self.page.evaluate("""
                (serial) => {
                    // 查找所有input
                    const inputs = Array.from(document.querySelectorAll('input'));
                    
                    // 方法1: 查找serial-input class
                    for (const inp of inputs) {
                        if (inp.className && inp.className.includes('serial')) {
                            inp.focus();
                            inp.select && inp.select();
                            
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(inp, serial);
                            
                            const inputEvent = new Event('input', { bubbles: true });
                            const changeEvent = new Event('change', { bubbles: true });
                            inp.dispatchEvent(inputEvent);
                            inp.dispatchEvent(changeEvent);
                            
                            return { success: true, method: 'serial-class', value: inp.value };
                        }
                    }
                    
                    // 方法2: 查找没有placeholder的前两个input
                    let found = 0;
                    for (const inp of inputs) {
                        if (!inp.placeholder && inp.type !== 'hidden' && inp.offsetParent !== null) {
                            if (found === 0) {
                                inp.focus();
                                inp.select && inp.select();
                                
                                const nativeSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value'
                                ).set;
                                nativeSetter.call(inp, serial);
                                
                                inp.dispatchEvent(new Event('input', { bubbles: true }));
                                inp.dispatchEvent(new Event('change', { bubbles: true }));
                                
                                return { success: true, method: 'no-placeholder', value: inp.value };
                            }
                            found++;
                        }
                    }
                    
                    // 方法3: 查找包含"章节"或"序号"的input
                    for (const inp of inputs) {
                        const placeholder = inp.placeholder || '';
                        if (placeholder.includes('章节') || placeholder.includes('序号') || placeholder.includes('第')) {
                            inp.focus();
                            inp.select && inp.select();
                            
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(inp, serial);
                            
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            
                            return { success: true, method: 'placeholder-match', value: inp.value };
                        }
                    }
                    
                    return { success: false };
                }
            """, str(chapter_number))
            
            logger.info(f">>> 序号填写结果: {fill_result}")
            await asyncio.sleep(0.3)

        # 填写章节标题
        logger.info(f">>> 填写章节标题: '{chapter_title_only}'")
        js_result = await self.page.evaluate("""
            (title) => {
                const inputs = Array.from(document.querySelectorAll('input'));
                
                // 方法1: 查找placeholder包含"标题"的input
                for (const inp of inputs) {
                    const placeholder = (inp.placeholder || '').toLowerCase();
                    if (placeholder.includes('标题')) {
                        inp.focus();
                        
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        nativeSetter.call(inp, title);
                        
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        
                        return { success: true, method: 'placeholder-title', value: inp.value };
                    }
                }
                
                // 方法2: 查找有editor class的input
                for (const inp of inputs) {
                    const cls = inp.className || '';
                    if (cls.includes('editor') || cls.includes('input')) {
                        const placeholder = inp.placeholder || '';
                        // 跳过序号输入框（通常没有placeholder或placeholder很短）
                        if (!placeholder || placeholder.length > 3) {
                            inp.focus();
                            
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(inp, title);
                            
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            
                            return { success: true, method: 'editor-class', value: inp.value };
                        }
                    }
                }
                
                // 方法3: 查找第二个没有placeholder的input
                let count = 0;
                for (const inp of inputs) {
                    if (!inp.placeholder && inp.type !== 'hidden' && inp.offsetParent !== null) {
                        count++;
                        if (count === 2) {
                            inp.focus();
                            
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(inp, title);
                            
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            
                            return { success: true, method: 'second-input', value: inp.value };
                        }
                    }
                }
                
                // 调试信息
                const debug = inputs.map(inp => ({
                    placeholder: inp.placeholder,
                    className: inp.className,
                    visible: inp.offsetParent !== null
                }));
                
                return { success: false, debug: debug };
            }
        """, chapter_title_only)

        logger.info(f"JavaScript填写标题结果: {js_result}")

        await self._save_debug_screenshot("confirm_page_after_title")

    async def _fill_content_on_confirm_page(self, content: str):
        """在发布确认页面上填写章节正文"""
        await self._save_debug_screenshot("confirm_page_before_content")
        await asyncio.sleep(2)  # 等待编辑器加载

        # 方法1: 使用get_by_placeholder
        try:
            locator = self.page.get_by_placeholder("正文内容")
            await locator.wait_for(timeout=5000)
            if await locator.is_visible():
                await locator.click()
                await asyncio.sleep(0.3)
                await locator.fill(content)
                logger.info("已填写正文 (方法1: get_by_placeholder)")
                await self._save_debug_screenshot("confirm_page_after_content")
                return
        except Exception as e:
            logger.debug(f"方法1失败: {e}")

        # 方法2: 使用JavaScript - 查找ProseMirror正文编辑器（番茄小说使用此编辑器）
        try:
            js_result = await self.page.evaluate("""
                (content) => {
                    // 查找所有可能的编辑器元素
                    const selectors = [
                        '.ProseMirror',
                        '.ql-editor',
                        '[contenteditable="true"]',
                        'textarea'
                    ];
                    
                    let targetEditor = null;
                    let maxSize = 0;
                    
                    for (const selector of selectors) {
                        const editors = document.querySelectorAll(selector);
                        for (const editor of editors) {
                            const rect = editor.getBoundingClientRect();
                            const size = rect.width * rect.height;
                            
                            // 跳过不可见的小元素
                            if (size < 10000) continue;
                            if (rect.width < 200 || rect.height < 100) continue;
                            
                            const styles = window.getComputedStyle(editor);
                            if (styles.display === 'none' || styles.visibility === 'hidden') continue;
                            
                            if (size > maxSize) {
                                maxSize = size;
                                targetEditor = editor;
                            }
                        }
                        if (targetEditor) break;
                    }

                    if (targetEditor) {
                        targetEditor.focus();

                        // 处理内容：去除首尾空白
                        const lines = content.split(/\\r?\\n/);
                        const processedLines = lines.map(line => line.trim()).filter(line => line);

                        // 清除现有内容
                        if (targetEditor.tagName === 'TEXTAREA') {
                            targetEditor.value = processedLines.join('\\n');
                            targetEditor.dispatchEvent(new Event('input', { bubbles: true }));
                        } else {
                            // contentEditable 或 ProseMirror
                            targetEditor.innerHTML = '';
                            processedLines.forEach((line, index) => {
                                const p = document.createElement('p');
                                p.textContent = line;
                                p.style.textIndent = '0';
                                targetEditor.appendChild(p);
                            });
                            targetEditor.dispatchEvent(new Event('input', { bubbles: true }));
                        }

                        return { success: true, method: targetEditor.tagName || 'editor', size: maxSize };
                    }

                    // 调试信息
                    const debug = {
                        selectors: selectors,
                        found: Array.from(document.querySelectorAll('.ProseMirror, .ql-editor, [contenteditable]')).map(el => ({
                            tag: el.tagName,
                            class: el.className,
                            rect: el.getBoundingClientRect()
                        }))
                    };
                    return { success: false, debug: debug };
                }
            """, content)

            if js_result and js_result.get('success'):
                logger.info(f"通过JavaScript填写正文成功: {js_result.get('method')}")
                await self._save_debug_screenshot("confirm_page_after_content")
                return
            else:
                logger.warning(f"JavaScript方法失败: {js_result}")
        except Exception as e:
            logger.debug(f"方法2失败: {e}")

        # 方法3: 尝试点击添加正文按钮（如果有）
        try:
            addBtn = await self.page.get_by_role("button", name="添加正文")
            if await addBtn.is_visible():
                await addBtn.click()
                await asyncio.sleep(2)
                
                # 再次尝试填写
                try:
                    locator = self.page.get_by_placeholder("正文内容")
                    if await locator.is_visible():
                        await locator.fill(content)
                        logger.info("已填写正文 (方法3: 添加正文后填写)")
                        await self._save_debug_screenshot("confirm_page_after_content")
                        return
                except:
                    pass
        except Exception as e:
            logger.debug(f"方法3失败: {e}")

        await self._save_debug_screenshot("confirm_page_content_failed")
        raise SelectorNotFoundException("在发布确认页面上找不到正文输入框")

    async def _click_confirm_publish(self):
        """在发布确认页面上点击发布按钮

        番茄小说的发布按钮是"下一步"，class包含publish-button
        """
        await self._save_debug_screenshot("confirm_page_before_publish")
        await asyncio.sleep(1)

        # 番茄小说的发布按钮选择器 - 扩展更多选择器
        publish_selectors = [
            "button.publish-button",  # 主要选择器：class包含publish-button
            "button.publish-button.auto-editor-next",  # 更精确的选择器
            "button.auto-editor-next",  # 编辑器下一步按钮
            "button:has-text('下一步')",  # 回退：文本匹配
            "button:has-text('下一步（审核快）')",  # 新版按钮
            "[class*='publish-button']",  # 模糊匹配
            "button.primary",  # 主要按钮
            "button[type='submit']",  # 提交按钮
        ]

        for selector in publish_selectors:
            try:
                el = await self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    is_visible = await el.is_visible()
                    is_enabled = await el.is_enabled() if hasattr(el, 'is_enabled') else True
                    btn_text = await el.text_content() if hasattr(el, 'text_content') else ""
                    btn_class = await el.get_attribute("class") if hasattr(el, 'get_attribute') else ""

                    logger.info(f"尝试选择器 '{selector}': visible={is_visible}, text='{btn_text}', class='{btn_class[:50] if btn_class else ''}'")

                    if is_visible and is_enabled:
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await el.click()
                        logger.info(f"已点击发布按钮 (选择器: {selector})")
                        await self._save_debug_screenshot("confirm_page_after_publish")
                        return
            except Exception as e:
                logger.debug(f"选择器 '{selector}' 失败: {e}")
                continue

        # 使用JavaScript查找并点击发布按钮
        logger.info("使用JavaScript查找并点击发布按钮...")
        js_result = await self.page.evaluate("""
            () => {
                // 查找所有按钮
                const buttons = Array.from(document.querySelectorAll('button'));

                // 优先查找包含publish-button class的按钮
                for (const btn of buttons) {
                    const cls = btn.className || '';
                    if (cls.includes('publish-button')) {
                        btn.click();
                        return { success: true, text: btn.textContent.trim(), class: cls };
                    }
                }

                // 回退：查找包含"下一步"的按钮
                for (const btn of buttons) {
                    const text = btn.textContent || '';
                    if (text.includes('下一步')) {
                        btn.click();
                        return { success: true, text: text.trim(), class: btn.className };
                    }
                }

                // 回退：查找主要的arco-btn-primary按钮
                for (const btn of buttons) {
                    const cls = btn.className || '';
                    if (cls.includes('arco-btn-primary')) {
                        btn.click();
                        return { success: true, text: btn.textContent.trim(), class: cls };
                    }
                }

                // 回退：查找任何enabled的primary按钮
                for (const btn of buttons) {
                    const cls = btn.className || '';
                    if (cls.includes('primary') || cls.includes('btn-primary')) {
                        btn.click();
                        return { success: true, text: btn.textContent.trim(), class: cls };
                    }
                }

                return { success: false };
            }
        """)

        logger.info(f"JavaScript点击结果: {js_result}")
        await self._save_debug_screenshot("confirm_page_publish_clicked")
