"""Window used for game installers"""

# pylint: disable=too-many-lines
from gi.repository import Gtk


class NavigationStack(Gtk.Stack):
    """
    This is a Stack widget that supports a back button and
    lazy-creation of pages.
    """

    def __init__(self, back_button, cancel_button=None, **kwargs):
        super().__init__(**kwargs)

        self.back_button = back_button
        self.cancel_button = cancel_button
        self.page_factories = {}
        self.stack_pages = {}
        self.navigation_stack = []
        self.navigation_exit_handler = None
        self.current_page_presenter = None
        self.current_navigated_page_presenter = None
        self.back_allowed = True
        self.cancel_allowed = True

    def add_named_factory(self, name, factory):
        self.page_factories[name] = factory

    def set_back_allowed(self, is_allowed=True):
        self.back_allowed = is_allowed
        self._update_back_button()

    def set_cancel_allowed(self, is_allowed=True):
        self.cancel_allowed = is_allowed
        self._update_back_button()

    def _update_back_button(self):
        can_go_back = self.back_allowed and self.navigation_stack
        self.back_button.set_visible(can_go_back)
        self.cancel_button.set_visible(not can_go_back and self.cancel_allowed)

    def navigate_to_page(self, page_presenter):
        if self.current_navigated_page_presenter and self.current_navigated_page_presenter != page_presenter:
            self.navigation_stack.append(self.current_navigated_page_presenter)
            self._update_back_button()

        self._go_to_page(page_presenter, True, Gtk.StackTransitionType.SLIDE_LEFT)

    def jump_to_page(self, page_presenter):
        self._go_to_page(page_presenter, False, Gtk.StackTransitionType.NONE)

    def navigate_back(self):
        if self.navigation_stack and self.back_allowed:
            try:
                back_to = self.navigation_stack.pop()
                self._go_to_page(back_to, True, Gtk.StackTransitionType.SLIDE_RIGHT)
            finally:
                self._update_back_button()

    def navigate_home(self):
        if self.navigation_stack and self.back_allowed:
            try:
                home = self.navigation_stack[0]
                self.navigation_stack.clear()
                self._go_to_page(home, True, Gtk.StackTransitionType.SLIDE_RIGHT)
            finally:
                self._update_back_button()

    def navigation_reset(self):
        if self.current_navigated_page_presenter:
            if self.current_page_presenter != self.current_navigated_page_presenter:
                self._go_to_page(self.current_navigated_page_presenter, True, Gtk.StackTransitionType.SLIDE_RIGHT)

    def save_current_page(self):
        return (self.current_page_presenter, self.current_navigated_page_presenter)

    def restore_current_page(self, state):
        page_presenter, navigated_presenter = state
        navigated = page_presenter == navigated_presenter
        self._go_to_page(page_presenter, navigated, Gtk.StackTransitionType.NONE)

    def _go_to_page(self, page_presenter, navigated, transition_type):
        exit_handler = self.navigation_exit_handler
        self.set_transition_type(transition_type)
        self.navigation_exit_handler = page_presenter()
        self.current_page_presenter = page_presenter
        if navigated:
            self.current_navigated_page_presenter = page_presenter
        if exit_handler:
            exit_handler()
        self._update_back_button()

    def discard_navigation(self):
        self.navigation_stack.clear()
        self._update_back_button()

    def present_page(self, name):
        if name not in self.stack_pages:
            factory = self.page_factories[name]
            page = factory()
            self.add_named(page, name)
            self.stack_pages[name] = page

        self.set_visible_child_name(name)
        return self.stack_pages[name]

    def present_replacement_page(self, name, page):
        old_page = self.stack_pages.get(name)

        if old_page != page:
            if old_page:
                self.remove(old_page)

            self.add_named(page, name)
            self.stack_pages[name] = page

        self.set_visible_child_name(name)
        return page
