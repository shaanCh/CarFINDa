"""Browser tools — individual tool classes for browser automation."""

from app.services.browser.tools.act import BrowserActTool
from app.services.browser.tools.autofill import BrowserAutofillTool
from app.services.browser.tools.control import BrowserControlTool
from app.services.browser.tools.login import BrowserLoginTool
from app.services.browser.tools.navigate import BrowserNavigateTool
from app.services.browser.tools.scrape import BrowserScrapeTool
from app.services.browser.tools.screenshot import BrowserScreenshotTool
from app.services.browser.tools.snapshot import BrowserSnapshotTool
from app.services.browser.tools.tabs import BrowserTabsTool

__all__ = [
    "BrowserActTool",
    "BrowserAutofillTool",
    "BrowserControlTool",
    "BrowserLoginTool",
    "BrowserNavigateTool",
    "BrowserScrapeTool",
    "BrowserScreenshotTool",
    "BrowserSnapshotTool",
    "BrowserTabsTool",
]
