#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def test():
    db = get_session()
    book = db.query(Book).filter(Book.book_name.like('%闺蜜%')).first()
    db.close()

    account_lock = await browser_manager.async_get_account_lock(1)
    async with account_lock:
        context = await browser_manager._async_create_context_from_session(1)
        page = await context.new_page()

        await page.goto(f"https://fanqienovel.com/main/writer/chapter-manage/{book.fanqie_book_id}")
        await asyncio.sleep(2)

        try:
            btn = await page.wait_for_selector("text=我知道了", timeout=2000)
            if btn:
                await btn.click()
                await asyncio.sleep(1)
        except:
            pass

        btn = await page.wait_for_selector("button:has-text('新建章节')")
        await btn.click()
        print("[OK] 点击新建章节")
        await asyncio.sleep(5)

        await page.screenshot(path="debug/final_test.png")

        # 简单检查
        result = await page.evaluate("""
            () => {
                return {
                    inputCount: document.querySelectorAll('input').length,
                    textareaCount: document.querySelectorAll('textarea').length,
                    bodyText: document.body.textContent.substring(0, 500)
                };
            }
        """)
        print(f"input数量: {result['inputCount']}")
        print(f"textarea数量: {result['textareaCount']}")
        print(f"body文本: {result['bodyText'][:200]}")

        await page.close()
        await context.close()


if __name__ == "__main__":
    asyncio.run(test())
