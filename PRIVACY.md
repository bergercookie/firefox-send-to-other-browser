Privacy Policy
==============

Last updated: 2026-10-08

Send to Other Browser does not collect, store, sell or share any personal data.
It has no servers, no analytics, no telemetry and no accounts.


What the extension does with your data
--------------------------------------

- URLs of the tabs you select (and the tab ids/titles needed to find them).
  Read in order to send them to the browser you pick.
  Passed over a local pipe to the companion native host on your own computer.

- Names and paths of installed browsers (Vivaldi, Chrome, Chromium, Brave, Edge).
  Read in order to show you the list of targets.
  Returned by the native host to the extension; stays on your computer.

The URLs are read only when you click a browser button in the popup or choose
"Send to ..." in the tab context menu, and only for the tabs you selected.
Nothing is read in the background.


The companion native host
-------------------------

A small open-source Python program (host/send_to_other_browser.py) receives those
URLs from Firefox and starts the target browser with them. It runs locally, makes
no network connections, writes no logs and keeps no files. Once the target browser
has been started it knows nothing more about the URLs; what that browser does with
them is covered by its own privacy policy.


Permissions, and why
--------------------

- tabs: read the URLs of the tabs you selected.
- nativeMessaging: talk to the companion host described above.
- menus: add the "Send to ..." entry to the tab context menu.

The extension requests no host (website) permissions, injects no scripts into web
pages and makes no network requests of its own.


Changes and contact
-------------------

If this policy changes the date above will be updated and the change will be
visible in the repository history. Questions or concerns: open an issue at
https://github.com/bergercookie/firefox-send-to-other-browser/issues
