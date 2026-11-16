---
name: ui-verify
description: Use after changing KnoxMap's web UI (templates, static JS or CSS) and before saying it works - how to restart the app and check the change in a real headless browser.
---

# Checking a UI change in the running app

Tests do not cover layout or behaviour in the page. Look at it.

## 1. Restart the app when needed

Flask caches templates: **restart after any change to `templates/`**. Static JS/CSS
only need a reload.

- Find the PID on the port with `ss -ltnp | grep :<port>` and kill that PID. Never
  `pkill -f`; other KnoxMap processes may be running.
- Start it again from the worktree you are working in (`PORT=<port> .venv/bin/python
  app.py`, plus the environment the developer uses), and confirm that `curl`
  returns 200.

## 2. Drive a headless browser

Use Chromium headless (the Playwright `chrome-headless-shell`) over the DevTools
protocol from a small node script in the scratchpad:

- Use a fresh `--user-data-dir` each run (delete the old profile).
- Enable `Runtime` before navigating, and **collect `Runtime.exceptionThrown`**.
  "No script errors" is part of every check.
- Click and type with `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` when
  hover or focus matters (tooltips). `element.click()` is fine otherwise.
- Read state back as data (which element is first in a pane, whether a row has
  `.is-changed`, whether a hint's `display` is `block`) and print PASS/FAIL lines.
- Take a `Page.captureScreenshot` of the sidebar clipped to its box, and **look at
  the image**: squares instead of circles, overflow and truncation only show there.

## 3. Watch for stale browsers

A headless Chrome left over from an earlier run keeps the debug port. The new one
then fails to start quietly, and the script talks to the **old browser with the old
page**. The symptom is a change that "did nothing" while the server serves the new
file. Before running, check `pgrep -af "remote-debugging-port=<port>"`, stop your own
leftover test browsers, and always `chrome.kill()` at the end of the script.

If a change still seems absent, compare what the page loaded with what the server
serves (`performance.getEntriesByType('resource')` vs `fetch(url, {cache:'no-store'})`).
Then trace the DOM call that should have run (wrap `Element.prototype.prepend` etc.
in `Page.addScriptToEvaluateOnNewDocument`) before guessing.

## 4. Report

Say what was checked and what it showed (counts, PASS lines, no script errors), and
list anything that was not checked.
