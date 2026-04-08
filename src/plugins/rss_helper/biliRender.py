import os
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = os.path.dirname(__file__)
TEMPLATE_DIR = os.path.join(OUTPUT_DIR, "templates")
jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# 【修改点】：增加 template_name 参数
async def render_to_image(template_data: dict, output_filename: str, template_name: str = "dynamic.html") -> str:
    """
    使用本地 Edge 和 Playwright 渲染 HTML 并自动截取完美尺寸
    """
    template = jinja_env.get_template(template_name)
    html_content = template.render(**template_data)
    
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=EDGE_PATH,
            headless=True
        )
        
        # device_scale_factor=2 保证画质清晰
        page = await browser.new_page(
            viewport={"width": 680, "height": 2000},
            device_scale_factor=2
        )
        
        await page.set_content(html_content, wait_until="networkidle")
        body_element = page.locator("body")
        await body_element.screenshot(path=output_path, type="png")
        await browser.close()
        
    return output_path