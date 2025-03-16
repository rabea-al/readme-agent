from xai_components.base import InArg, OutArg, Component, xai_component
from playwright.sync_api import sync_playwright
from playwright.sync_api import Page
import queue
import threading
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
class PlaywrightWorker:
    def __init__(self):
        self.task_queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._playwright = None
        self._browser = None
        self._page = None

    def _run(self):
        self._playwright = sync_playwright().start()
        while True:
            func, args, kwargs, result_queue = self.task_queue.get()
            try:
                result = func(*args, **kwargs)
                result_queue.put((True, result))
            except Exception as e:
                result_queue.put((False, e))

    def run(self, func, *args, **kwargs):
        result_queue = queue.Queue()
        self.task_queue.put((func, args, kwargs, result_queue))
        success, result = result_queue.get()
        if success:
            return result
        else:
            raise result

    def get_playwright(self):
        return self._playwright

    def set_browser(self, browser):
        self._browser = browser

    def get_browser(self):
        return self._browser

    def set_page(self, page):
        self._page = page

    def get_page(self):
        return self._page

global_worker = None

@xai_component
class PlaywrightOpenBrowser(Component):
    """Opens a Playwright browser and navigates to a specified URL using a dedicated worker thread.

    ##### inPorts:
    - url: The URL to visit.
    - headless: Whether to run the browser in headless mode (default: False).

    ##### outPorts:
    - page: The Playwright page instance.
    - browser: The Playwright browser instance.
    - worker: The PlaywrightWorker instance (for reuse in subsequent components).
    """
    url: InArg[str]
    headless: InArg[bool]
    page: OutArg[Page]
    browser: OutArg[any]
    worker: OutArg[any]

    def execute(self, ctx) -> None:
        global global_worker
        if global_worker is None:
            global_worker = PlaywrightWorker()

        headless_mode = self.headless.value if self.headless.value is not None else False

        def open_browser():
            browser = global_worker.get_playwright().chromium.launch(headless=headless_mode)
            page = browser.new_page()
            page.goto(self.url.value)
            global_worker.set_browser(browser)
            global_worker.set_page(page)
            return (browser, page)

        browser, page = global_worker.run(open_browser)
        self.browser.value = browser
        self.page.value = page
        self.worker.value = global_worker
        ctx["browser"] = browser
        ctx["page"] = page
        print(f"Browser opened and navigated to: {self.url.value} | Headless: {headless_mode}")

@xai_component
class PlaywrightIdentifyElement(Component):
    """
    Identifies an element on the page using one of the locator methods
    (CSS selector, role with optional name, or label) and returns its locator.

    inPorts:
    - page: The Playwright page instance.
    - selector: The CSS selector for the element (optional).
    - role: The role of the element (optional).
    - name: The accessible name for role (optional).
    - label: The label text (optional).

    outPorts:
    - locator: The identified Playwright locator.
    - out_page: The unchanged Playwright page instance.
    """
    page: InArg[Page]
    selector: InArg[str]
    role: InArg[str]
    name: InArg[str]
    label: InArg[str]
    out_page: OutArg[Page]
    locator: OutArg[any]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        selector_value = self.selector.value if self.selector.value is not None else ""
        role_value = self.role.value if self.role.value is not None else ""
        name_value = self.name.value if self.name.value is not None else ""
        label_value = self.label.value if self.label.value is not None else ""

        if not page_obj:
            raise ValueError("No valid Playwright page instance provided.")

        def identify(p):
            if selector_value:
                try:
                    formatted_selector = selector_value.format(**ctx)
                except Exception as e:
                    raise ValueError(f"Error formatting selector: {selector_value}. Error: {e}")
                print(f"Identifying element using CSS selector: {formatted_selector}")
                return p.locator(formatted_selector)
            elif role_value:
                print(f"Identifying element using role: {role_value} {'with name: ' + name_value if name_value else ''}")
                if name_value:
                    return p.get_by_role(role_value, name=name_value)
                else:
                    return p.get_by_role(role_value)
            elif label_value:
                print(f"Identifying element using label: {label_value}")
                return p.get_by_label(label_value)
            else:
                raise ValueError("Must provide at least one locator method (selector, role, or label).")

        result_locator = global_worker.run(identify, page_obj)
        self.locator.value = result_locator
        self.out_page.value = page_obj
        print("Element identified successfully.")

@xai_component
class PlaywrightClickElement(Component):
    """
    Clicks on an element or a specific position on the page.
    Supports double-click and optionally clicking at a specified position without a locator.

    inPorts:
    - page: The Playwright page instance.
    - locator: (Optional) The locator for the element (obtained from IdentifyElement) or a CSS selector string with placeholders.
    - double_click: Boolean indicating if a double-click should be performed (default: False).
    - position: A dictionary specifying the position offset (e.g., {"x": 0, "y": 0}).
                If provided without a locator, it clicks at the specified coordinates on the page.

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    double_click: InArg[bool]
    position: InArg[dict]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")

        raw_locator = self.locator.value if self.locator.value is not None else None
        locator_obj = None
        if raw_locator and isinstance(raw_locator, str):
            try:
                formatted_selector = raw_locator.format(**ctx)
            except Exception as e:
                raise ValueError(f"Error in formatting selector: {raw_locator}. Error: {e}")
            locator_obj = page_obj.locator(formatted_selector)
            print(f"Using formatted selector: {formatted_selector}")
        else:
            locator_obj = raw_locator

        double_click_value = self.double_click.value if self.double_click.value is not None else False
        position_value = self.position.value if self.position.value is not None else {}

        if not page_obj:
            raise ValueError("Missing Playwright page instance.")

        def click_action(p):
            if position_value and not locator_obj:
                if double_click_value:
                    p.mouse.dblclick(position_value["x"], position_value["y"])
                    print(f"Double clicked at position {position_value} on the page.")
                else:
                    p.mouse.click(position_value["x"], position_value["y"])
                    print(f"Clicked at position {position_value} on the page.")
            elif locator_obj:
                if position_value:
                    if double_click_value:
                        locator_obj.dblclick(position=position_value)
                        print(f"Double clicked on element at position {position_value}.")
                    else:
                        locator_obj.click(position=position_value)
                        print(f"Clicked on element at position {position_value}.")
                else:
                    if double_click_value:
                        locator_obj.dblclick()
                        print("Double clicked on element.")
                    else:
                        locator_obj.click()
                        print("Clicked on element.")
            else:
                raise ValueError("You must provide either a locator or a valid position dictionary.")

        global_worker.run(click_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightFillInput(Component):
    """
    Fills the identified element with the specified text.
    Supports sequential typing using press_sequentially with an optional delay.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator of the element (from IdentifyElement).
    - text: The text to fill in.
    - sequential: Boolean input; if True, uses press_sequentially (optional, default: False).
    - delay: The delay in milliseconds between key presses when using sequential typing (optional, default: 0).

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    text: InArg[str]
    sequential: InArg[bool]
    delay: InArg[int]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        text_value = self.text.value
        sequential_value = self.sequential.value if self.sequential.value is not None else False
        delay_value = self.delay.value if self.delay.value is not None else 0

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def fill_action(p):
            if sequential_value:
                locator_obj.press_sequentially(text_value, delay=delay_value)
                print(f"Typed text sequentially with delay {delay_value}ms on the identified element. Text: {text_value}")
            else:
                locator_obj.fill(text_value)
                print(f"Filled element with text: {text_value}")

        global_worker.run(fill_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightPressKey(Component):
    """
    Presses a specified key on the identified element or on the page globally if no element is specified.

    inPorts:
    - page: The Playwright page instance.
    - locator: (Optional) The locator of the element (from IdentifyElement). If not provided, key press happens globally.
    - key: The key to press (e.g., "Enter", "Tab").

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]  # optional
    key: InArg[str]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value if self.locator.value is not None else None
        key_value = self.key.value

        if not page_obj:
            raise ValueError("Missing Playwright page instance.")
        if not key_value:
            raise ValueError("'key' must be provided.")

        def press_action(p):
            if locator_obj:
                locator_obj.press(key_value)
                print(f"Pressed key: {key_value} on the identified element.")
            else:
                p.keyboard.press(key_value)
                print(f"Pressed key: {key_value} globally on the page.")

        global_worker.run(press_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightHoverElement(Component):
    """
    Hovers over the identified element.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator object obtained from IdentifyElement.

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def hover_action(p):
            locator_obj.hover()
            print("Hovered over the identified element.")

        global_worker.run(hover_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightCheckElement(Component):
    """
    Checks a checkbox or radio button if 'to_be_checked' is False (or not provided).
    If 'to_be_checked' is True, it skips performing the check action and only asserts
    that the element is already checked.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator for the element (obtained from IdentifyElement).
    - to_be_checked: Boolean; if True, then do not perform check action, only assert that the element is checked.
      (Default: False)

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[any]
    locator: InArg[any]
    to_be_checked: InArg[bool]
    out_page: OutArg[any]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        to_be_checked_value = self.to_be_checked.value if self.to_be_checked.value is not None else False

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def check_and_assert(p):
            if not to_be_checked_value:
                locator_obj.check()
                print("Performed check action on the element.")
            else:
                print("ℹ️ Skipped check action because 'to_be_checked' is True.")
            p.wait_for_timeout(500)
            if not locator_obj.is_checked():
                raise ValueError("Assertion failed: Element is not checked!")
            print("Assertion passed: Element is checked.")

        global_worker.run(check_and_assert, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightSelectOptions(Component):
    """
    Selects option(s) from a <select> element.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator for the <select> element (obtained from IdentifyElement).
    - options: A list of options to select. (Pass a list even if selecting one option.)
    - by: (Optional) A string indicating the key to use when converting each option.
          For example, "label", "value", or "index". If provided, each option in the list
          will be converted to a dictionary: {by: option}.

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    options: InArg[list]
    by: InArg[str]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        options_value = self.options.value
        by_value = self.by.value if self.by.value is not None else ""

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def select_action(p):
            if by_value:
                option_list = [{by_value: opt} for opt in options_value]
            else:
                option_list = options_value

            locator_obj.select_option(option_list)
            print(f"Selected options: {option_list} on the identified element.")

        global_worker.run(select_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightUploadFiles(Component):
    """
    Uploads file(s) to a file input element.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator for the file input element (obtained from IdentifyElement).
    - files: A list of file paths to upload.

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    files: InArg[list]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        files_list = self.files.value

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def upload_action(p):
            locator_obj.set_input_files(files_list)
            print(f"Uploaded files: {files_list}")

        global_worker.run(upload_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightFocusElement(Component):
    """
    Focuses on an element using its locator.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator for the element (obtained from IdentifyElement).

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def focus_action(p):
            locator_obj.focus()
            print("Focused on the identified element.")

        global_worker.run(focus_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightScrolling(Component):
    """
    Scrolls either a specific element or the entire page using different methods.

    inPorts:
    - page: The Playwright page instance.
    - locator: (Optional) The locator for a specific element (obtained from IdentifyElement).
    - method: (Optional) The scrolling method to use. Options:
              "scroll_into_view" - scroll the element into view using scroll_into_view_if_needed().
              "mouse_wheel"     - scroll using the mouse wheel with given offsets.
              "evaluate"        - scroll the element using evaluate() (if locator provided) or the page if not.
              "page_evaluate"   - scroll the entire page using page.evaluate("window.scrollBy(x, y)").
              Defaults to "evaluate" if not provided.
    - x: (Optional) The horizontal scroll offset (default: 0).
    - y: (Optional) The vertical scroll offset (default: 0).

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    method: InArg[str]
    x: InArg[int]
    y: InArg[int]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        method_value = self.method.value.lower() if self.method.value is not None else "evaluate"
        x_value = self.x.value if self.x.value is not None else 0
        y_value = self.y.value if self.y.value is not None else 0

        if not page_obj:
            raise ValueError("Missing Playwright page instance.")

        def scroll_action(p):
            if method_value == "scroll_into_view":
                if locator_obj:
                    locator_obj.scroll_into_view_if_needed()
                    print("Scrolled element into view using scroll_into_view_if_needed().")
                else:
                    raise ValueError("'scroll_into_view' method requires a locator.")
            elif method_value == "mouse_wheel":
                if locator_obj:
                    locator_obj.hover()
                p.mouse.wheel(x_value, y_value)
                print(f"Scrolled using mouse wheel by offsets x: {x_value}, y: {y_value}.")
            elif method_value == "evaluate":
                if locator_obj:
                    script = f"e => {{ e.scrollTop += {y_value}; e.scrollLeft += {x_value}; }}"
                    locator_obj.evaluate(script)
                    print(f"Scrolled element using evaluate() with offsets x: {x_value}, y: {y_value}.")
                else:
                    p.evaluate(f"window.scrollBy({x_value}, {y_value})")
                    print(f"Scrolled page using evaluate() with offsets x: {x_value}, y: {y_value}.")
            elif method_value == "page_evaluate":
                p.evaluate(f"window.scrollBy({x_value}, {y_value})")
                print(f"Scrolled page using page_evaluate with offsets x: {x_value}, y: {y_value}.")
            else:
                raise ValueError(f"Unknown scrolling method: {method_value}")

        global_worker.run(scroll_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightDragAndDrop(Component):
    """
    Performs a drag and drop action using the simplified drag_to() method.

    inPorts:
    - page: The Playwright page instance.
    - source: The locator for the element to be dragged (obtained from IdentifyElement).
    - target: The locator for the target element where the item will be dropped (obtained from IdentifyElement).

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    source: InArg[any]
    target: InArg[any]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        source_locator = self.source.value
        target_locator = self.target.value

        if not page_obj or not source_locator or not target_locator:
            raise ValueError("Missing page instance or source/target locator.")

        def drag_action(p):
            source_locator.drag_to(target_locator)
            print("Drag and drop action performed using drag_to().")

        global_worker.run(drag_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightTakeScreenshot(Component):
    """
    Captures a screenshot of a specified element or the entire page if no element is specified.

    inPorts:
    - page: The Playwright page instance.
    - file_path: The file path where the screenshot will be saved.
    - full_page: (Optional) Boolean to capture a full-page screenshot when no locator is provided (default: False).
    - locator: (Optional) The locator for the element to capture. If provided, the screenshot will be taken of this element.

    outPorts:
    - page: The updated Playwright page instance.
    - out_path: The file path where the screenshot was saved.
    """
    page: InArg[Page]
    locator: InArg[any]
    file_path: InArg[str]
    full_page: InArg[bool]
    out_page: OutArg[Page]
    out_path: OutArg[str]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        file_path_value = self.file_path.value
        full_page_value = self.full_page.value if self.full_page.value is not None else False
        locator_obj = self.locator.value

        if not page_obj:
            raise ValueError("No valid Playwright page instance provided.")
        if not file_path_value:
            raise ValueError("'file_path' must be provided to save the screenshot.")

        def screenshot_action(p):
            if locator_obj:
                locator_obj.screenshot(path=file_path_value)
                print(f"Screenshot of the element captured and saved to: {file_path_value}")
            else:
                p.screenshot(path=file_path_value, full_page=full_page_value)
                print(f"Screenshot of the page captured and saved to: {file_path_value} | full_page: {full_page_value}")

        global_worker.run(screenshot_action, page_obj)
        self.out_page.value = page_obj
        self.out_path.value = file_path_value


@xai_component
class PlaywrightWaitForElement(Component):
    """
    Waits for the identified element to become visible on the page.

    inPorts:
    - page: The Playwright page instance.
    - locator: The locator for the element (obtained from IdentifyElement).
    - timeout: (Optional) The maximum time in milliseconds to wait for the element to be visible (default: 30000).

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    locator: InArg[any]
    timeout: InArg[int]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        locator_obj = self.locator.value
        timeout_value = self.timeout.value if self.timeout.value is not None else 30000

        if not page_obj or not locator_obj:
            raise ValueError("Missing page instance or locator.")

        def wait_action(p):
            locator_obj.wait_for(state="visible", timeout=timeout_value)
            print(f"Element is now visible (waited up to {timeout_value} ms).")

        global_worker.run(wait_action, page_obj)
        self.out_page.value = page_obj

@xai_component
class PlaywrightCloseBrowser(Component):
    """
    Closes the Playwright browser.

    ##### inPorts:
    - page: The Playwright page instance.
    - browser: (Optional) The Playwright browser instance.
      If not provided, it will be retrieved from the context.

    outPorts:
    - (None): This component closes the browser.
    """
    page: InArg[Page]
    browser: InArg[any]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        browser_obj = self.browser.value if self.browser.value is not None else ctx.get("browser")

        if not page_obj or not browser_obj:
            raise ValueError("Missing page instance or browser.")

        def close_action(p):
            browser_obj.close()
            print("Browser closed.")

        global_worker.run(close_action, page_obj)

@xai_component
class PlaywrightWaitForTime(Component):
    """
    Waits for a specified amount of time before proceeding.

    inPorts:
    - time_in_seconds: The number of seconds to wait.

    outPorts:
    - (None): This component simply introduces a delay.
    """
    time_in_seconds: InArg[int]

    def execute(self, ctx) -> None:
        import time

        wait_time = self.time_in_seconds.value if self.time_in_seconds.value is not None else 5
        print(f"Waiting for {wait_time} seconds...")
        time.sleep(wait_time)
        print("Done waiting.")

@xai_component
class PlaywrightNavigateToURL(Component):
    """
    Navigates to a specified URL using an existing Playwright page instance.

    inPorts:
    - page: The existing Playwright page instance.
    - url: The new URL to navigate to.

    outPorts:
    - page: The updated Playwright page instance.
    """
    page: InArg[Page]
    url: InArg[str]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        url_value = self.url.value

        if not page_obj:
            raise ValueError("Missing Playwright page instance.")
        if not url_value:
            raise ValueError("URL must be provided.")

        def navigate_action(p):
            p.goto(url_value)
            print(f"Navigated to URL: {url_value}")

        global_worker.run(navigate_action, page_obj)
        self.out_page.value = page_obj

import json
@xai_component
class PlaywrightExtractComponentInfo(Component):

    page: InArg[any]
    component_name: InArg[str]
    component_info: OutArg[dict]

    def execute(self, ctx) -> None:
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        comp_name = self.component_name.value

        response_text = global_worker.run(lambda p: p.inner_text("body"), page_obj)
        data = json.loads(response_text)

        def flatten(data):
            result = []
            if isinstance(data, list):
                for item in data:
                    result.extend(flatten(item))
            elif isinstance(data, dict):
                if "task" in data:
                    result.append(data)
                else:
                    for v in data.values():
                        result.extend(flatten(v))
            return result

        comps = flatten(data)
        comp_info = next((comp for comp in comps if comp.get("task", "").lower() == comp_name.lower()), None)
        if comp_info is None:
            raise ValueError("Component not found!")

        self.component_info.value = comp_info
        ctx["comp_info"] = comp_info
        ctx["comp_info_category"] = comp_info.get("category", "")
        ctx["comp_info_task"] = comp_info.get("task", "")
        print("Extracted component info:", comp_info)

@xai_component
class PlaywrightCaptureEndpoint(Component):
    """
    Captures any completed network request in the page that contains "components?" in its URL.

    ##### inPorts:
    - page: The Playwright page instance.
    - reload_page: (Optional) Boolean flag to determine whether the page should be reloaded automatically (default: True).

    ##### outPorts:
    - endpoint_url: The captured endpoint URL.
    - out_page: The Playwright page instance after capturing the request.
    """

    page: InArg[Page]
    reload_page: InArg[bool]
    endpoint_url: OutArg[str]
    out_page: OutArg[Page]

    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        if not page_obj:
            raise ValueError("Missing Playwright page instance.")

        do_reload = True if self.reload_page.value is None else self.reload_page.value

        captured_url = None

        def on_request_finished(request):
            nonlocal captured_url
            url = request.url
            if "components/?" in url:
                print(f"Captured endpoint: {url}")
                captured_url = url

        def run_action(p):
            p.on("requestfinished", on_request_finished)
            if do_reload:
                p.reload()
            p.wait_for_timeout(3000)
            p.remove_listener("requestfinished", on_request_finished)

        global_worker.run(run_action, page_obj)
        self.endpoint_url.value = captured_url if captured_url else ""
        self.out_page.value = page_obj

        if captured_url:
            print(f"Endpoint found and stored: {captured_url}")
        else:
            print("No endpoint found that contains 'components/?'.")

@xai_component
class PlaywrightDynamicElementHandle(Component):
    """
    Applies a dynamic JavaScript function to the specified element to obtain a modified element.

    ##### inPorts:
    - page: The Playwright page instance.
    - locator: The primary element locator (can be obtained from the IdentifyElement component).
    - js_script: A JavaScript function (as a string) applied to the element.
                 Example: "node => node.closest('.node')"

    ##### outPorts:
    - out_locator: The resulting element (ElementHandle) after applying the function.
    - out_page: The same Playwright page instance.
    """

    page: InArg[Page]
    locator: InArg[any]
    js_script: InArg[str]
    out_page: OutArg[Page]
    out_locator: OutArg[any]


    def execute(self, ctx) -> None:
        global global_worker
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        input_locator = self.locator.value
        script = self.js_script.value

        if not page_obj:
            raise ValueError("Missing Playwright page instance.")
        if not input_locator:
            raise ValueError("Missing locator input.")
        if not script:
            raise ValueError("Missing JavaScript script input.")

        element_handle = global_worker.run(lambda p: input_locator.first.element_handle(), page_obj)
        if not element_handle:
            raise ValueError("Element handle not found!")

        transformed_handle = global_worker.run(lambda p: element_handle.evaluate_handle(script), page_obj)
        transformed_element = transformed_handle.as_element()
        if not transformed_element:
            raise ValueError("Transformed element not found!")

        self.out_locator.value = transformed_element
        self.out_page.value = page_obj
        print("Dynamic element handle extracted using script:", script)


@xai_component()
class ExtractCategoryData(Component):
    """
    Component to extract category details from a JSON string.

    Expected JSON format:
    {
        "category_info": [ { ... }, { ... }, ... ],
        "readme_template": "A string containing the README template (Markdown format) or a URL to the template.",
        "screenshot_links": ["link1", "link2", ...]
    }

    ##### inPorts:
    - input_json: JSON string containing the category details.

    ##### outPorts:
    - category_info: A JSON object (typically a list) representing the details of the entire category.
    - readme_template: A string representing the README template.
    - screenshot_links: A list of strings representing the screenshot links.
    """
    input_json: InArg[str]

    category_info: OutArg[list]
    readme_template: OutArg[str]
    screenshot_links: OutArg[list]

    def execute(self, ctx) -> None:
        input_data = json.loads(self.input_json.value)
        self.category_info.value = input_data.get("category_info", [])
        self.readme_template.value = str(input_data.get("readme_template", ""))
        self.screenshot_links.value = input_data.get("screenshot_links", [])

        print(f"Category Info: {self.category_info.value}")
        print(f"README Template: {self.readme_template.value}")
        print(f"Screenshot Links: {self.screenshot_links.value}")

@xai_component()
class GitHubReadmeFetcher(Component):
    """
    Component to fetch a README template from a GitHub raw URL.

    This tool reads a README file from the given GitHub raw URL and returns its content as a string.

    ##### inPorts:
    - url: a string representing the GitHub raw URL for the README file.

    ##### outPorts:
    - readme_content: a string containing the content of the README file.
    """
    url: InArg[str]
    readme_content: OutArg[str]

    def execute(self, ctx) -> None:
        url_value = self.url.value
        response = requests.get(url_value)
        if response.status_code == 200:
            self.readme_content.value = response.text
            print(f"Fetched README content from: {url_value}")
        else:
            raise ValueError(f"Failed to fetch README content, status code: {response.status_code}")

@xai_component()
class ReadmeGeneratorFromCategory(Component):
    """
    Generates a new README for a component category in Markdown format using category information,
    a README template, and screenshot links for the first two components.

    It outputs:
    - new_readme: a string containing the newly generated README content in Markdown format.

    Finally, it saves the generated README content to a file named "README.md".
    """
    category_info: InArg[list]
    readme_template: InArg[str]
    screenshot_links: InArg[list]
    new_readme: OutArg[str]

    def execute(self, ctx) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")

        client = OpenAI(api_key=api_key)

        cat_info = self.category_info.value
        template = self.readme_template.value
        screenshot_links = self.screenshot_links.value

        prompt = (
            "You are a documentation generator. Generate a new README in Markdown format for a component library "
            "using the following details. The README must follow the style and structure of the provided template. "
            "It should be concise, clear, and natural, without unnecessary filler or signs of AI generation.\n\n"
            "Template (Markdown):\n"
            f"{template}\n\n"
            "Category Information (components library details):\n"
            f"{json.dumps(cat_info, indent=2)}\n\n"
            "Screenshot Links for the first two components:\n"
            f"{json.dumps(screenshot_links, indent=2)}\n\n"
            "Using the above information, generate a new README in Markdown format that summarizes the key features "
            "of the library, describes its main components, and includes the provided screenshot links as visual references."
            "When saving the text, do not enclose it within Markdown formatting indicators like:```markdown text```"
            "Additionally, you **must strictly adhere** to the given template, maintaining its exact **structure, paragraph organization, and formatting**."
            "Do not alter the writing style or add any unnecessary content."

            "**IMPORTANT:** After generating the README, you **must always save the file** immediately to ensure no data is lost."
        )

        print("Constructed GPT prompt:")
        print(prompt)

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.5,
        )

        generated_readme = response.choices[0].message.content
        self.new_readme.value = generated_readme

        print("Generated new README content successfully.")
        print("Generated README content (Markdown):")
        print(generated_readme)

        with open("README.md", "w", encoding="utf-8") as f:
            f.write(generated_readme)
        print("README.md file saved.")

@xai_component()
class ExtractCategoryData(Component):
    """
    Component to extract category details from a JSON string.

    Expected JSON format:
    {
        "category_info": [ { ... }, { ... }, ... ],
        "readme_template": "A string containing the README template or a URL to the template.",
        "screenshot_links": ["link1", "link2", ...]
    }

    ##### inPorts:
    - input_json: JSON string containing the category details.

    ##### outPorts:
    - category_info: A list representing the details of the entire category.
    - readme_template: A string representing the README template.
    - screenshot_links: A list representing the screenshot links.
    """
    input_json: InArg[str]

    category_info: OutArg[list]
    readme_template: OutArg[str]
    screenshot_links: OutArg[list]

    def execute(self, ctx) -> None:
        input_data = json.loads(self.input_json.value)
        self.category_info.value = input_data.get("category_info", [])
        self.readme_template.value = str(input_data.get("readme_template", ""))
        self.screenshot_links.value = input_data.get("screenshot_links", [])

        print(f"Category Info: {self.category_info.value}")
        print(f"README Template: {self.readme_template.value}")
        print(f"Screenshot Links: {self.screenshot_links.value}")

@xai_component
class PlaywrightExtractCategoryInfo(Component):
    """
    Extracts information for an entire component category from the API's JSON response.

    The JSON response is expected to contain a list (or nested structure) of component definitions.
    This tool filters the components whose "category" field (case-insensitive) matches the given category.

    Use this tool whenever you need to gather complete information for a category (e.g., all components
    under "PLAYWRIGHT") to then use that data (and possibly previous README examples) for generating a new README.

    Its arguments are:
    - page: A Playwright page instance that contains the API response (JSON).
    - category: A string representing the desired component category (e.g., "PLAYWRIGHT").

    It outputs:
    - category_info: A list of JSON objects, each representing a component in the specified category.
    """
    page: InArg[any]
    category: InArg[str]
    category_info: OutArg[list]

    def execute(self, ctx) -> None:
        # Retrieve page from inArg or fallback to ctx
        page_obj = self.page.value if self.page.value is not None else ctx.get("page")
        if not page_obj:
            raise ValueError("Missing Playwright page instance.")

        # Normalize category to lower-case for matching
        desired_cat = self.category.value.strip().lower()

        # Retrieve JSON response from the page
        response_text = global_worker.run(lambda p: page_obj.inner_text("body"), page_obj)
        data = json.loads(response_text)

        def flatten(data):
            result = []
            if isinstance(data, list):
                for item in data:
                    result.extend(flatten(item))
            elif isinstance(data, dict):
                if "task" in data:
                    result.append(data)
                else:
                    for v in data.values():
                        result.extend(flatten(v))
            return result

        # Flatten the JSON structure to get a list of component definitions
        components = flatten(data)
        # Filter the components that belong to the desired category (case-insensitive)
        filtered = [comp for comp in components if comp.get("category", "").strip().lower() == desired_cat]
        self.category_info.value = filtered

        print(f"Extracted category info for '{desired_cat}'.")
        print(f"Number of components in this category: {len(filtered)}")

@xai_component()
class ExtractComponentDetails(Component):

    input_json: InArg[str]
    url: OutArg[str]
    component_name: OutArg[str]

    def execute(self, ctx) -> None:
        input_data = json.loads(self.input_json.value)
        self.url.value = str(input_data.get("url", ""))
        self.component_name.value = str(input_data.get("component_name", ""))

        print(f"URL: {self.url.value}")
        print(f"Component Name: {self.component_name.value}")

@xai_component()
class ExtractCategoryDetails(Component):
    input_json: InArg[str]
    url: OutArg[str]
    category_name: OutArg[str]

    def execute(self, ctx) -> None:
        input_data = json.loads(self.input_json.value)
        self.url.value = str(input_data.get("url", ""))
        self.category_name.value = str(input_data.get("category_name", ""))

        print(f"URL: {self.url.value}")
        print(f"Category Name: {self.category_name.value}")

@xai_component()
class ExtractComponentPaths(Component):
    """
    Component to extract URL and file path details from a JSON string.

    Expected JSON format:
    {
        "url": "http://example.com/api/endpoint",
        "file_path": "path/to/component/file.py"
    }

    ##### inPorts:
    - input_json: JSON string containing the URL and file path details.

    ##### outPorts:
    - url: A string representing the URL extracted from the JSON.
    - file_path: A string representing the file path extracted from the JSON.
    """
    input_json: InArg[str]

    url: OutArg[str]
    file_path: OutArg[str]

    def execute(self, ctx) -> None:
        input_data = json.loads(self.input_json.value)
        self.url.value = str(input_data.get("url", ""))
        self.file_path.value = str(input_data.get("file_path", ""))

        print(f"URL: {self.url.value}")
        print(f"File Path: {self.file_path.value}")
