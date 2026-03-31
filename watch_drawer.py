#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控抽屉 - 持续检查页面变化
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def watch_drawer():
    db = get_session()
    book = db.query(Book).filter(Book.book_name.like('%闺蜜%')).first()
    db.close()

    print("正在启动浏览器...")
    account_lock = await browser_manager.async_get_account_lock(1)
    async with account_lock:
        context = await browser_manager._async_create_context_from_session(1)
        page = await context.new_page()

        await page.goto(f"https://fanqienovel.com/main/writer/chapter-manage/{book.fanqie_book_id}")
        await asyncio.sleep(2)

        # 关闭弹窗
        try:
            btn = await page.wait_for_selector("text=我知道了", timeout=2000)
            if btn:
                await btn.click()
                await asyncio.sleep(1)
        except:
            pass

        print("\n" + "="*70)
        print("准备就绪!")
        print("请在浏览器中手动操作:")
        print("1. 点击'新建章节'按钮")
        print("2. 等待抽屉完全打开")
        print("3. 脚本会自动检测并分析...")
        print("="*70 + "\n")

        # 持续监控60秒
        last_body_text = ""
        check_count = 0

        for i in range(60):  # 监控60秒，每秒检查一次
            await asyncio.sleep(1)

            try:
                body_text = await page.inner_text("body")

                # 检查是否有变化（抽屉打开时页面内容会增加）
                if "章节标题" in body_text or "添加正文" in body_text or "请输入章节" in body_text:
                    print(f"\n检测到抽屉已打开! (第{i}秒)")
                    print("正在截图并分析...\n")

                    # 截图
                    await page.screenshot(path="debug/drawer_detected.png")

                    # 立即分析
                    print("=== 分析输入元素 ===")
                    all_inputs = await page.evaluate("""
                        () => {
                            const results = [];

                            // 检查input
                            document.querySelectorAll('input').forEach((el, idx) => {
                                const rect = el.getBoundingClientRect();
                                results.push({
                                    tag: 'INPUT',
                                    type: el.type || 'text',
                                    placeholder: String(el.placeholder || ''),
                                    className: String(el.className || '').substring(0, 60),
                                    visible: el.offsetParent !== null,
                                    rect: rect.width + 'x' + rect.height
                                });
                            });

                            // 检查textarea
                            document.querySelectorAll('textarea').forEach((el, idx) => {
                                const rect = el.getBoundingClientRect();
                                results.push({
                                    tag: 'TEXTAREA',
                                    placeholder: String(el.placeholder || ''),
                                    className: String(el.className || '').substring(0, 60),
                                    visible: el.offsetParent !== null,
                                    rect: rect.width + 'x' + rect.height
                                });
                            });

                            // 检查contentEditable
                            document.querySelectorAll('[contenteditable]').forEach((el, idx) => {
                                const rect = el.getBoundingClientRect();
                                results.push({
                                    tag: el.tagName,
                                    contenteditable: el.contentEditable,
                                    className: String(el.className || '').substring(0, 60),
                                    visible: el.offsetParent !== null,
                                    rect: rect.width + 'x' + rect.height
                                });
                            });

                            return results;
                        }
                    """)

                    print(f"找到 {len(all_inputs)} 个输入元素:")
                    for inp in all_inputs:
                        print(f"  {inp['tag']} placeholder='{inp['placeholder']}'")
                        print(f"    class='{inp['className']}'")
                        print(f"    visible={inp['visible']} rect={inp['rect']}")

                    # 查找抽屉容器
                    print("\n=== 分析抽屉容器 ===")
                    drawer_info = await page.evaluate("""
                        () => {
                            const results = [];
                            const selectors = [
                                '[class*="drawer"]', '[class*="Drawer"]',
                                '[class*="modal"]', '[class*="Modal"]',
                                '[role="dialog"]', '.arco-drawer', '.arco-modal'
                            ];

                            for (const sel of selectors) {
                                document.querySelectorAll(sel).forEach(el => {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width > 100 && rect.height > 100) {
                                        results.push({
                                            selector: sel,
                                            tag: el.tagName,
                                            className: String(el.className || '').substring(0, 80),
                                            rect: rect.width + 'x' + rect.height + ' at ' + rect.left + ',' + rect.top,
                                            childCount: el.children.length
                                        });
                                    }
                                });
                            }
                            return results;
                        }
                    """)

                    print(f"找到 {len(drawer_info)} 个可能的抽屉容器:")
                    for d in drawer_info:
                        print(f"  {d['tag']} class='{d['className']}'")
                        print(f"    rect={d['rect']} children={d['childCount']}")

                    # 尝试点击标题输入框
                    print("\n=== 尝试JavaScript操作 ===")
                    js_result = await page.evaluate("""
                        () => {
                            // 方法1: 查找所有有placeholder的input
                            const inputs = document.querySelectorAll('input[placeholder]');
                            for (const inp of inputs) {
                                const rect = inp.getBoundingClientRect();
                                if (rect.width > 50) {
                                    return {
                                        success: true,
                                        method: 'input[placeholder]',
                                        placeholder: String(inp.placeholder),
                                        className: String(inp.className || '').substring(0, 60),
                                        rect: rect.width + 'x' + rect.height
                                    };
                                }
                            }

                            // 方法2: 查找arco-input内的input
                            const arcoInput = document.querySelector('.arco-input input, [class*="arco-input"] input');
                            if (arcoInput) {
                                const rect = arcoInput.getBoundingClientRect();
                                return {
                                    success: true,
                                    method: 'arco-input input',
                                    placeholder: String(arcoInput.placeholder || ''),
                                    rect: rect.width + 'x' + rect.height
                                };
                            }

                            // 方法3: 查找visible的input
                            const allInputs = document.querySelectorAll('input');
                            for (const inp of allInputs) {
                                const rect = inp.getBoundingClientRect();
                                if (rect.width > 50 && rect.height > 20) {
                                    return {
                                        success: true,
                                        method: 'visible input',
                                        placeholder: String(inp.placeholder || ''),
                                        className: String(inp.className || '').substring(0, 60),
                                        rect: rect.width + 'x' + rect.height
                                    };
                                }
                            }

                            return {success: false};
                        }
                    """)
                    print(f"JavaScript结果: {js_result}")

                    print("\n" + "="*70)
                    print("截图已保存到 debug/drawer_detected.png")
                    print("请查看截图确认状态！")
                    print("="*70)

                    # 检测到抽屉后继续监控一会儿
                    await asyncio.sleep(5)
                    break

                check_count += 1
                if i % 10 == 0:
                    print(f"监控中... ({i}秒)", end='\r')

            except Exception as e:
                print(f"检查出错: {e}")

        if check_count >= 60:
            print("\n监控超时，未检测到抽屉打开")

        print("\n截图已保存，请手动检查")
        await page.screenshot(path="debug/final_state.png")

        await page.close()
        await context.close()


if __name__ == "__main__":
    asyncio.run(watch_drawer())
