"""Shared Textual widgets."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static


class MenuEntry:
    def __init__(self, action_id: str, label: str) -> None:
        self.action_id = action_id
        self.label = label


class MenuScreen(Screen):
    """List-based menu with optional back button."""

    BINDINGS = [("escape", "back", "Back")]
    AUTO_FOCUS = "#menu"

    def __init__(
        self,
        title: str,
        subtitle: str,
        entries: list[MenuEntry],
        *,
        show_back: bool = True,
    ) -> None:
        super().__init__()
        self.menu_title = title
        self.menu_subtitle = subtitle
        self.entries = entries
        self.show_back = show_back
        self._actions_by_item_id: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        items: list[ListItem] = []
        self._actions_by_item_id = {}
        for index, entry in enumerate(self.entries):
            item_id = f"item-{index}"
            self._actions_by_item_id[item_id] = entry.action_id
            items.append(ListItem(Label(entry.label), id=item_id))
        yield Header(show_clock=False)
        yield Static(f"[bold]{self.menu_title}[/bold]\n{self.menu_subtitle}", id="subtitle")
        yield ListView(*items, id="menu")
        if self.show_back:
            with Horizontal():
                yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        if self.entries:
            self.query_one("#menu", ListView).index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        action = self._actions_by_item_id.get(item_id)
        if action is None:
            return
        self.on_menu_action(action)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.action_back()

    def on_menu_action(self, action_id: str) -> None:
        raise NotImplementedError

    def action_back(self) -> None:
        self.app.pop_screen()


class OutputScreen(Screen):
    BINDINGS = [("escape", "close", "Close"), ("enter", "close", "Close")]
    AUTO_FOCUS = "#close"

    def __init__(
        self,
        title: str,
        text: str,
        *,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.output_title = title
        self.text = text or "(no output)"
        self.on_close = on_close

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(f"[bold]{self.output_title}[/bold]")
        yield Static(self.text, id="output")
        yield Button("Close", id="close", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.action_close()

    def action_close(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.app.pop_screen()


class InputScreen(Screen):
    BINDINGS = [("escape", "cancel", "Cancel")]
    AUTO_FOCUS = "#value"

    def __init__(
        self,
        title: str,
        label: str,
        default: str = "",
        *,
        on_submit: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.form_title = title
        self.field_label = label
        self.default = default
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.result: str | None = None

    def compose(self) -> ComposeResult:
        from textual.widgets import Input

        yield Header(show_clock=False)
        with Vertical():
            yield Static(f"[bold]{self.form_title}[/bold]")
            yield Label(self.field_label)
            yield Input(value=self.default, id="value")
            yield Static(
                "[dim]Enter = save · Esc = cancel · F10 = quit app[/dim]",
                id="hint",
            )
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        from textual.widgets import Input

        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event) -> None:
        from textual.widgets import Input

        if event.input.id == "value":
            event.stop()
            self._save()

    def _save(self) -> None:
        from textual.widgets import Input

        value = self.query_one("#value", Input).value.strip()
        self.result = value
        if self.on_submit is not None:
            self.on_submit(value)
            return
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
            return
        if event.button.id == "save":
            self._save()

    def action_cancel(self) -> None:
        self.result = None
        if self.on_cancel is not None:
            self.on_cancel()
            return
        self.app.pop_screen()
