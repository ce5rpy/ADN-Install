"""Textual link editor for nav_links / footer / news."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from adn_deploy.application import config_arrays
from adn_deploy.core.env import Settings


class LinkEditorScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add", "Add"),
    ]

    def __init__(self, settings: Settings, collection: str) -> None:
        super().__init__()
        self.settings = settings
        self.collection = collection
        self._selected_idx: int | None = None

    def compose(self) -> ComposeResult:
        title = {"nav_links": "Top links", "footer": "Footer links", "news": "News"}.get(
            self.collection, self.collection
        )
        yield Header(show_clock=False)
        yield Static(f"[bold]{title}[/bold] — choose a link to edit", id="subtitle")
        yield ListView(id="links")
        yield HorizontalButtons()
        yield Footer()

    def on_mount(self) -> None:
        self._reload_list()

    def _reload_list(self) -> None:
        lv = self.query_one("#links", ListView)
        lv.clear()
        items = config_arrays.list_items(self.settings, self.collection)
        if not items:
            lv.append(ListItem(Label("(no links yet — press Add link)")))
        for idx, name, url in items:
            label = f"{name} — {url}" if url else name
            lv.append(ListItem(Label(label), id=f"item-{idx}"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("item-"):
            return
        self._selected_idx = int(item_id.removeprefix("item-"))
        self.app.push_screen(EditLinkScreen(self.settings, self.collection, self._selected_idx))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_add(self) -> None:
        self.app.push_screen(AddLinkScreen(self.settings, self.collection))


class HorizontalButtons(Horizontal):
    def compose(self) -> ComposeResult:
        yield Button("Add link", id="add", variant="primary")
        yield Button("Back", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        screen = self.app.screen
        if event.button.id == "add" and isinstance(screen, LinkEditorScreen):
            screen.action_add()
        elif event.button.id == "back":
            self.app.pop_screen()


class AddLinkScreen(Screen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, settings: Settings, collection: str) -> None:
        super().__init__()
        self.settings = settings
        self.collection = collection

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Link text")
        yield Input(placeholder="Visible label", id="name")
        yield Label("URL")
        yield Input(placeholder="https://…", id="url")
        yield Button("Save", id="save", variant="primary")
        yield Button("Cancel", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
            return
        name = self.query_one("#name", Input).value.strip()
        url = self.query_one("#url", Input).value.strip()
        if not name:
            self.notify("Link text is required", severity="error")
            return
        if self.collection != "news" and not url:
            self.notify("URL is required", severity="error")
            return
        config_arrays.add_link(self.settings, self.collection, name, url)
        self.notify("Link added")
        self.app.pop_screen()
        parent = self.app.screen
        if isinstance(parent, LinkEditorScreen):
            parent._reload_list()

    def action_cancel(self) -> None:
        self.app.pop_screen()


class EditLinkScreen(Screen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, settings: Settings, collection: str, index: int) -> None:
        super().__init__()
        self.settings = settings
        self.collection = collection
        self.index = index
        self._name = ""
        self._url = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="title")
        yield Label("Link text")
        yield Input(id="name")
        yield Label("URL")
        yield Input(id="url")
        if self.collection == "nav_links":
            yield Button("Submenu title (nav only)", id="parent")
        yield Button("Save", id="save", variant="primary")
        yield Button("Delete", id="delete", variant="error")
        yield Button("Back", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        for idx, name, url in config_arrays.list_items(self.settings, self.collection):
            if idx == self.index:
                self._name = name
                self._url = url
                break
        self.query_one("#title", Static).update(f"[bold]Edit:[/bold] {self._name}")
        self.query_one("#name", Input).value = self._name
        self.query_one("#url", Input).value = self._url

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
        elif event.button.id == "delete":
            config_arrays.delete_link(self.settings, self.collection, self.index)
            self.notify("Deleted")
            self.app.pop_screen()
            parent = self.app.screen
            if isinstance(parent, LinkEditorScreen):
                parent._reload_list()
        elif event.button.id == "parent":
            self.app.push_screen(ParentTitleScreen(self.settings))
        elif event.button.id == "save":
            name = self.query_one("#name", Input).value.strip()
            url = self.query_one("#url", Input).value.strip()
            if not name:
                self.notify("Link text required", severity="error")
                return
            config_arrays.edit_link(self.settings, self.collection, self.index, name, url)
            self.notify("Saved")
            self.action_cancel()

    def action_cancel(self) -> None:
        self.app.pop_screen()


class ParentTitleScreen(Screen):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        cur = config_arrays.get_parent_title(self.settings)
        yield Header()
        yield Label("Navbar submenu title (dropdown label)")
        yield Input(value=cur, id="title")
        yield Button("Save", id="save", variant="primary")
        yield Button("Cancel", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
            return
        val = self.query_one("#title", Input).value.strip()
        if val:
            config_arrays.set_parent_title(self.settings, val)
            self.notify("Submenu title saved")
        self.app.pop_screen()


def run_link_editor(settings: Settings, collection: str = "nav_links") -> None:
    class _App(App):
        BINDINGS = [Binding("q", "quit", "Quit")]

        def on_mount(self) -> None:
            self.push_screen(LinkEditorScreen(settings, collection))

    _App().run()
