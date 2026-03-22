#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Dequacker — GTK4 + libadwaita

import sys
import os
import locale
import gettext
from datetime import datetime
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango


# ── i18n setup ────────────────────────────────────────────────────────────────
LOCALEDIR = os.environ.get(
    "DEQUACKER_LOCALEDIR",
    os.path.join(os.path.dirname(__file__), "..", "po", "locale"),
)
GETTEXT_PACKAGE = "dequacker"

# locale.setlocale can raise on macOS for unsupported locale strings.
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

gettext.bindtextdomain(GETTEXT_PACKAGE, LOCALEDIR)
gettext.textdomain(GETTEXT_PACKAGE)

def _make_translator() -> gettext.GNUTranslations:

    langs: list[str] = []
    for var in ("LANGUAGE", "LANG", "LC_ALL", "LC_MESSAGES"):
        val = os.environ.get(var, "").strip()
        if val and val not in ("C", "POSIX"):
            # LANGUAGE may be colon-separated: "ru:lt"
            for part in val.split(":"):
                code = part.split(".")[0].strip()   # "ru_RU.UTF-8" → "ru_RU"
                if code and code not in langs:
                    langs.append(code)
                    bare = code.split("_")[0]        # "ru_RU" → "ru"
                    if bare != code and bare not in langs:
                        langs.append(bare)

    # No language requested → return English source strings via NullTranslations
    if not langs:
        return gettext.NullTranslations()

    try:
        return gettext.translation(
            GETTEXT_PACKAGE,
            localedir=LOCALEDIR,
            languages=langs,
        )
    except FileNotFoundError:
        # Requested language has no .mo → fall back to English source strings
        return gettext.NullTranslations()

_t = _make_translator()
_ = _t.gettext


# ── App constants ─────────────────────────────────────────────────────────────
APP_ID      = "io.github.you.Dequacker"
APP_NAME    = _("Dequacker")
APP_VERSION = "0.0.1"

# ── Emotional support phrases ─────────────────────────────────────────────────
def _support_phrases():
    return [
        _("You're doing great"),
        _("Everyone gets stuck sometimes"),
        _("You've solved hard problems before"),
        _("Take a breath — you've got this"),
        _("You're learning with every problem"),
        _("You're almost there"),
        _("The solution is closer than you think"),
    ]

_support_index = 0

# ── Helpers ───────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# When running as a Flatpak, icons are installed to /app/share/dequacker/
# When running from source, they live at ../data/ relative to src/
_FLATPAK_DATA = "/app/share/dequacker"
_SOURCE_DATA  = os.path.join(_BASE_DIR, "..", "data")
_DATA_DIR     = _FLATPAK_DATA if os.path.isdir(_FLATPAK_DATA) else _SOURCE_DATA


def _resource(relative: str) -> str:
    # Strip the leading "data/" prefix — icons are stored directly under _DATA_DIR
    if relative.startswith("data/icons/"):
        name = relative[len("data/icons/"):]
        return os.path.join(_DATA_DIR, "icons", name)
    return os.path.join(_BASE_DIR, "..", relative)


# ── Message bubble ────────────────────────────────────────────────────────────
class MessageBubble(Gtk.Box):
    def __init__(self, text: str, is_user: bool):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        label = Gtk.Label(
            label=text,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            xalign=0,
            selectable=True,
        )
        label.set_max_width_chars(45)
        label.set_margin_start(10)
        label.set_margin_end(10)
        label.set_margin_top(6)
        label.set_margin_bottom(6)

        frame = Gtk.Frame()
        frame.set_child(label)

        if is_user:
            frame.add_css_class("bubble-user")
            self.set_halign(Gtk.Align.END)
        else:
            frame.add_css_class("bubble-duck")
            self.set_halign(Gtk.Align.START)

        self.append(frame)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        self._text = text
        self._timestamp = datetime.now().strftime("%H:%M")
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_: frame.set_tooltip_text(self._timestamp))
        frame.add_controller(hover)

        click = Gtk.GestureClick(button=3)
        click.connect("released", self._on_right_click)
        frame.add_controller(click)

    def _on_right_click(self, gesture, _n, x, y):
        menu = Gio.Menu()
        menu.append(_("Copy"), "bubble.copy")
        ag = Gio.SimpleActionGroup()
        act = Gio.SimpleAction.new("copy", None)
        act.connect("activate", lambda *_: self._do_copy())
        ag.add_action(act)
        self.insert_action_group("bubble", ag)
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    def _do_copy(self):
        Gdk.Display.get_default().get_clipboard().set(self._text)


# ── Chat page ─────────────────────────────────────────────────────────────────
class ChatPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._reply_pending = False

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll = scroll

        self._list = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.END,
        )
        self._list.add_css_class("message-list")

        scroll.set_child(self._list)
        self.append(scroll)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(8)
        row.set_margin_bottom(8)

        self._entry = Gtk.Entry(
            hexpand=True,
            # TRANSLATORS: placeholder text in the chat input box
            placeholder_text=_("Describe your bug to the duck…"),
        )
        self._entry.connect("activate", self._on_send)

        send_btn = _icon_button("_force_fallback_", "send.svg", _("Send"))
        send_btn.add_css_class("suggested-action")
        send_btn.set_sensitive(False)
        send_btn.connect("clicked", self._on_send)
        self._send_btn = send_btn

        self._entry.connect(
            "changed",
            lambda e: self._send_btn.set_sensitive(bool(e.get_text().strip())),
        )

        row.append(self._entry)
        row.append(send_btn)
        self.append(row)

        # TRANSLATORS: opening greeting from the duck
        GLib.idle_add(lambda: self._duck_say(_("Quack! Tell me about your bug.")) or False)

    # ── internal helpers ──────────────────────────────────────────────────────
    def _add(self, text: str, is_user: bool):
        bubble = MessageBubble(text, is_user)
        revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=160,
            child=bubble,
        )
        self._list.append(revealer)
        GLib.idle_add(lambda: revealer.set_reveal_child(True) or False)
        GLib.timeout_add(180, self._scroll_bottom)

    def _duck_say(self, text: str):
        self._add(text, is_user=False)

    def _scroll_bottom(self):
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return GLib.SOURCE_REMOVE

    def _on_send(self, *_args):
        text = self._entry.get_text().strip()
        if not text:
            return
        self._entry.set_text("")
        self._add(text, is_user=True)
        if not self._reply_pending:
            self._reply_pending = True
            GLib.timeout_add(380, self._reply)

    def _reply(self):
        # TRANSLATORS: the duck's one and only answer
        self._reply_pending = False
        self._duck_say(_("Quack?"))
        return GLib.SOURCE_REMOVE


# ── Welcome page ──────────────────────────────────────────────────────────────
class WelcomePage(Gtk.Box):
    def __init__(self, on_start, show_toast):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        self.set_margin_top(40)
        self.set_margin_bottom(40)
        self.set_margin_start(32)
        self.set_margin_end(32)

        icon_path = _resource("data/icons/duck.svg")
        picture = Gtk.Picture()
        picture.set_size_request(180, 180)
        picture.set_halign(Gtk.Align.CENTER)
        picture.set_can_shrink(True)
        picture.add_css_class("duck-wobble")
        if icon_path and os.path.exists(icon_path):
            picture.set_filename(icon_path)
        self.append(picture)

        title = Gtk.Label(label=_("Dequacker"))
        title.add_css_class("title-1")
        self.append(title)

        # TRANSLATORS: subtitle on the welcome screen
        subtitle = Gtk.Label(
            label=_("Talk to the duck — it listens.\nExplaining the problem is half the solution."),
            justify=Gtk.Justification.CENTER,
            wrap=True,
        )
        subtitle.add_css_class("body")
        subtitle.add_css_class("dim-label")
        self.append(subtitle)

        # Both buttons side by side
        btn_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )

        # TRANSLATORS: primary button — enters duck consultation chat
        chat_btn = Gtk.Button(label=_("Consult the Duck"))
        chat_btn.add_css_class("suggested-action")
        chat_btn.add_css_class("pill")
        chat_btn.connect("clicked", lambda _: on_start())
        btn_row.append(chat_btn)

        # TRANSLATORS: secondary button — shows an encouraging phrase
        support_btn = Gtk.Button(label=_("Encouragement"))
        support_btn.add_css_class("pill")
        support_btn.connect("clicked", lambda _: show_toast())
        btn_row.append(support_btn)

        self.append(btn_row)


# ── Main window ───────────────────────────────────────────────────────────────
class RubberDuckWindow(Adw.ApplicationWindow):
    def __init__(self, app: "RubberDuckApp"):
        super().__init__(
            application=app,
            title=_("Dequacker"),
            default_width=420,
            default_height=620,
        )

        provider = Gtk.CssProvider()
        provider.load_from_string(_CSS)
        try:
            Gtk.style_context_add_provider_for_display(
                self.get_display(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        except AttributeError:
            Gtk.StyleContext.add_provider_for_display(
                self.get_display(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self._win_title = Adw.WindowTitle(
            title=_("Dequacker"),
            subtitle=_("Your rubber duck is listening"),
        )
        header.set_title_widget(self._win_title)

        self._new_btn = _icon_button(
            "_force_fallback_", "duck-small.svg", _("New session")
        )
        self._new_btn.connect("clicked", self._on_new_session)
        self._new_btn.set_visible(False)
        header.pack_start(self._new_btn)

        menu_btn = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            tooltip_text=_("Main menu"),
            primary=True,
        )
        menu_btn.set_menu_model(self._build_menu())
        header.pack_end(menu_btn)

        toolbar_view.add_top_bar(header)

        self._toast_overlay = Adw.ToastOverlay()

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(280)

        self._welcome = WelcomePage(
            on_start=self._show_chat,
            show_toast=self._show_support_toast,
        )
        self._stack.add_named(self._welcome, "welcome")

        self._toast_overlay.set_child(self._stack)
        toolbar_view.set_content(self._toast_overlay)
        self.set_content(toolbar_view)

    # ── Menu ─────────────────────────────────────────────────────────────────
    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        # TRANSLATORS: menu item
        menu.append(_("About Dequacker"), "app.about")
        # TRANSLATORS: menu item
        menu.append(_("Quit"), "app.quit")
        return menu

    # ── Navigation ────────────────────────────────────────────────────────────
    def _show_chat(self):
        if getattr(self, "_navigating", False):
            return
        self._navigating = True
        GLib.timeout_add(300, lambda: setattr(self, "_navigating", False) or False)

        old = self._stack.get_child_by_name("chat")
        if old:
            self._stack.remove(old)
        self._chat = None
        self._chat = ChatPage()
        self._stack.add_named(self._chat, "chat")
        self._stack.set_visible_child_name("chat")
        self._new_btn.set_visible(True)
        # TRANSLATORS: header subtitle shown during duck consultation
        self._win_title.set_subtitle(_("Consulting the duck"))

    def _show_support_toast(self):
        global _support_index
        phrases = _support_phrases()
        phrase = phrases[_support_index % len(phrases)]
        _support_index += 1
        toast = Adw.Toast(title=phrase, timeout=4)
        self._toast_overlay.add_toast(toast)

    def _on_new_session(self, *_args):
        self._navigating = False
        old = self._stack.get_child_by_name("chat")
        if old:
            self._stack.remove(old)
        self._chat = None
        self._stack.set_visible_child_name("welcome")
        self._new_btn.set_visible(False)
        self._win_title.set_subtitle(_("Your rubber duck is listening"))


# ── Application ───────────────────────────────────────────────────────────────
class RubberDuckApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.connect("activate", self._on_activate)
        self._register_actions()

    def _register_actions(self):
        quit_act = Gio.SimpleAction.new("quit", None)
        quit_act.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_act)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_act = Gio.SimpleAction.new("about", None)
        about_act.connect("activate", self._on_about)
        self.add_action(about_act)
        self.set_accels_for_action("app.about", ["F1"])

        new_act = Gio.SimpleAction.new("new-session", None)
        new_act.connect("activate", lambda *_: self.get_active_window()._on_new_session())
        self.add_action(new_act)
        self.set_accels_for_action("app.new-session", ["<primary>n"])

    def _on_activate(self, app):
        win = app.get_active_window()
        if win:
            win.present()
            return
        win = RubberDuckWindow(app)
        icon_theme = Gtk.IconTheme.get_for_display(win.get_display())
        icon_theme.add_search_path(_resource("data/icons"))
        win.connect("close-request", self._on_close_request)
        win.present()

    def _on_close_request(self, _win) -> bool:
        self.quit()
        return False

    def _on_about(self, *_args):
        # Adw.AboutDialog is the current API (Adw ≥ 1.5).
        # It replaces the older Adw.AboutWindow.
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="io.github.alexeyfdv.dequacker",
            version=APP_VERSION,
            developer_name="Alexey",
            copyright="© 2026",
            license_type=Gtk.License.GPL_3_0,
            comments=(
                "A rubber duck debugger.\n"
                "Explain your bug to the duck.\n"
                "The duck will listen, nod, and say Quack."
            ),
            website="https://github.com/alexeyfdv/dequacker",
            issue_url="https://github.com/alexeyfdv/dequacker/issues",
            developers=["Alexey <alexeyfdv>"],
            translator_credits=_("translator-credits"),
        )
        dialog.present(self.get_active_window())



def _icon_button(system_name: str, fallback_svg: str, tooltip: str) -> Gtk.Button:
 
    # Check if the system icon theme has this icon
    display = Gdk.Display.get_default()
    theme = Gtk.IconTheme.get_for_display(display)
    if theme.has_icon(system_name):
        btn = Gtk.Button(icon_name=system_name, tooltip_text=tooltip)
    else:
        # Load our bundled SVG instead
        svg_path = _resource(f"data/icons/{fallback_svg}")
        img = Gtk.Image()
        if os.path.exists(svg_path):
            img.set_from_file(svg_path)
        else:
            # Last resort: text label
            img.set_from_icon_name("image-missing")
        btn = Gtk.Button(tooltip_text=tooltip)
        btn.set_child(img)
    return btn


# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
.bubble-user {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
    border-radius: 18px 18px 4px 18px;
    border: none;
}
.bubble-duck {
    background-color: @card_bg_color;
    border-radius: 18px 18px 18px 4px;
}
.message-list { padding: 8px; }

@keyframes wobble {
    0%   { transform: rotate(0deg);  }
    20%  { transform: rotate(-6deg); }
    40%  { transform: rotate(6deg);  }
    60%  { transform: rotate(-3deg); }
    80%  { transform: rotate(3deg);  }
    100% { transform: rotate(0deg);  }
}
.duck-wobble { animation: wobble 2.4s ease-in-out infinite; }
"""


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    return RubberDuckApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
