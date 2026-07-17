# pylint: disable=no-member
"""GTK4 widgets for rendering game media in grid and list views."""

from __future__ import annotations

from gettext import gettext as _
from math import floor

import gi

gi.require_version("PangoCairo", "1.0")

import cairo
from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo

from lutris.gui.views.game_item import GameItem
from lutris.gui.widgets.utils import (
    get_default_icon_path,
    get_runtime_icon_path,
    get_scaled_surface_by_path,
    get_surface_size,
)
from lutris.services.service_media import resolve_media_path
from lutris.util.jobs import schedule_at_idle
from lutris.util.log import logger
from lutris.util.path_cache import MISSING_GAMES

_MEDIA_CACHE_GENERATION_NUMBER = 0


class GameMediaPresentation(GObject.Object):
    """Shared presentation state for game media cells."""

    def __init__(self) -> None:
        super().__init__()
        self.service = None
        self.show_badges = True
        self.expected_width: int | None = None
        self.expected_height: int | None = None
        self._inset_fractions: dict[str, float] = {}
        self.cached_surfaces_new: dict = {}
        self.cached_surfaces_old: dict = {}
        self.cached_surfaces_loaded = 0
        self.cached_surface_generation = 0
        self.badge_size: tuple[int, int] | None = (0, 0)
        self.badge_alpha = 0.6
        self.badge_fore_color = (1, 1, 1)
        self.badge_back_color = (0, 0, 0)

    def is_library_view(self) -> bool:
        return self.service is None

    def set_expected_size(self, width: int, height: int) -> None:
        self.expected_width = width
        self.expected_height = height

    def inset_game(self, game_id: str, fraction: float) -> bool:
        if fraction > 0.0:
            if fraction != self._inset_fractions.get(game_id):
                self._inset_fractions[game_id] = fraction
                return True
        elif game_id in self._inset_fractions:
            del self._inset_fractions[game_id]
            return True
        return False

    def get_inset_fraction(self, game_id: str | None) -> float:
        if not game_id:
            return 0.0
        return self._inset_fractions.get(game_id, 0.0)

    def clear_cache(self) -> None:
        self.cached_surfaces_old.clear()
        self.cached_surfaces_new.clear()

    def cycle_cache(self) -> None:
        if self.cached_surfaces_loaded > 0:
            self.cached_surfaces_old = self.cached_surfaces_new
            self.cached_surfaces_new = {}
            self.cached_surfaces_loaded = 0

    def _get_cached_surface_by_path(self, widget, path, size, preserve_aspect_ratio=True):
        if self.cached_surface_generation != _MEDIA_CACHE_GENERATION_NUMBER:
            self.cached_surface_generation = _MEDIA_CACHE_GENERATION_NUMBER
            self.clear_cache()

        key = widget, path, size, preserve_aspect_ratio

        if key in self.cached_surfaces_new:
            return self.cached_surfaces_new[key]

        if key in self.cached_surfaces_old:
            surface = self.cached_surfaces_old[key]
        else:
            surface = self._get_surface_by_path(widget, path, size, preserve_aspect_ratio)
            if surface:
                self.cached_surfaces_loaded += 1

        self.cached_surfaces_new[key] = surface
        return surface

    @staticmethod
    def _get_surface_by_path(widget, path, size, preserve_aspect_ratio=True):
        cell_size = size
        scale_factor = widget.get_scale_factor() if widget else 1
        try:
            return get_scaled_surface_by_path(
                path, cell_size, scale_factor, preserve_aspect_ratio=preserve_aspect_ratio
            )
        except Exception as ex:  # pylint: disable=broad-except
            logger.exception("Unable to load media '%s': %s", path, ex)
            return None

    @staticmethod
    def is_bright_corner(surface, corner_size):
        surface_format = surface.get_format()
        if surface_format != cairo.FORMAT_ARGB32:  # pylint: disable=no-member
            return False

        device_scale_x, device_scale_y = surface.get_device_scale()
        corner_pixel_width = int(corner_size[0] * device_scale_x)
        corner_pixel_height = int(corner_size[1] * device_scale_y)
        pixel_width = surface.get_width()
        pixel_height = surface.get_height()

        def is_bright_pixel(x, y):
            if 0 <= x < pixel_width and 0 <= y < pixel_height:
                stride = surface.get_stride()
                data = surface.get_data()
                offset = (y * stride) + x * 4
                pixel = data[offset : offset + 4]
                for channel in pixel:
                    if channel < 128:
                        return False
                return True
            return False

        return (
            is_bright_pixel(pixel_width - 1, pixel_height - 1)
            and is_bright_pixel(pixel_width - corner_pixel_width, pixel_height - 1)
            and is_bright_pixel(pixel_width - 1, pixel_height - corner_pixel_height)
            and is_bright_pixel(pixel_width - corner_pixel_width, pixel_height - corner_pixel_height)
        )

    def select_badge_metrics(self, surface, media_width, media_height):
        def get_badge_icon_size():
            if media_width < 64:
                return None
            if media_height < 128:
                return 16, 16
            if media_height < 256:
                return 24, 24
            return 32, 32

        self.badge_size = get_badge_icon_size()
        on_bright_surface = self.badge_size and self.is_bright_corner(surface, self.badge_size)

        bright_color = 0.8, 0.8, 0.8
        dark_color = 0.2, 0.2, 0.2
        self.badge_fore_color = dark_color if on_bright_surface else bright_color
        self.badge_back_color = bright_color if on_bright_surface else dark_color

    def get_media_area(self, surface, cell_area):
        media_area = Gdk.Rectangle()
        width, height = get_surface_size(surface)
        media_area.x = round(cell_area.x + (cell_area.width - width) / 2)

        if self.is_library_view():
            media_area.y = round(cell_area.y + (cell_area.height - height) / 2)
        else:
            media_area.y = round(cell_area.y + cell_area.height - height)

        media_area.width, media_area.height = width, height
        return media_area

    @staticmethod
    def render_media(cr, surface, x, y):
        width, height = get_surface_size(surface)
        cr.set_source_surface(surface, x, y)
        cr.get_source().set_extend(cairo.Extend.PAD)  # pylint: disable=no-member
        cr.rectangle(x, y, width, height)
        cr.fill()

    _platform_icon_paths: dict[str, list[str]] = {}

    @classmethod
    def get_platform_icon_paths(cls, platform):
        if platform in cls._platform_icon_paths:
            return cls._platform_icon_paths[platform]

        if "," in platform:
            platforms = platform.split(",")
        else:
            platforms = [platform]

        icon_paths = []
        for platform_name in platforms:
            icon_path = get_runtime_icon_path(platform_name + "-symbolic")
            if icon_path:
                icon_paths.append(icon_path)

        cls._platform_icon_paths[platform] = icon_paths
        return icon_paths

    def render_platforms(self, cr, widget, surface, surface_x, media_area, platform):
        if platform and self.badge_size:
            icon_paths = self.get_platform_icon_paths(platform)
            if icon_paths:
                self.render_badge_stack(cr, widget, surface, surface_x, icon_paths, media_area)

    def render_badge_stack(self, cr, widget, surface, surface_x, icon_paths, media_area):
        badge_width = self.badge_size[0]
        badge_height = self.badge_size[1]
        alpha = self.badge_alpha
        fore_color = self.badge_fore_color
        back_color = self.badge_back_color

        def render_badge(badge_x, badge_y, path):
            cr.rectangle(badge_x, badge_y, badge_width, badge_height)
            cr.set_source_rgba(back_color[0], back_color[1], back_color[2], alpha)
            cr.fill()

            icon = self._get_cached_surface_by_path(widget, path, size=self.badge_size)
            cr.set_source_rgba(fore_color[0], fore_color[1], fore_color[2], alpha)
            cr.mask_surface(icon, badge_x, badge_y)

        media_right = surface_x + get_surface_size(surface)[0]
        x = media_right - badge_width
        spacing = (media_area.height - badge_height * len(icon_paths)) / max(1, len(icon_paths) - 1)
        spacing = min(spacing, 1)
        y_offset = floor(badge_height + spacing)
        y = media_area.y + media_area.height - badge_height - y_offset * (len(icon_paths) - 1)

        for icon_path in icon_paths:
            render_badge(x, y, icon_path)
            y = y + y_offset

    def render_text_badge(self, cr, widget, text, left, bottom):
        def get_layout():
            layout = widget.create_pango_layout(text)
            font = layout.get_context().get_font_description()
            font.set_weight(Pango.Weight.BOLD)
            layout.set_font_description(font)
            _, text_bounds = layout.get_extents()
            return layout, text_bounds.width / Pango.SCALE, text_bounds.height / Pango.SCALE

        if self.badge_size:
            alpha = self.badge_alpha
            fore_color = self.badge_fore_color
            back_color = self.badge_back_color

            layout, text_width, text_height = get_layout()

            cr.save()

            text_scale = self.badge_size[1] / text_height
            text_height = self.badge_size[1]
            text_width = round(text_width * text_scale)

            cr.rectangle(left, bottom - text_height, text_width + 4, text_height)
            cr.set_source_rgba(back_color[0], back_color[1], back_color[2], alpha)
            cr.fill()

            cr.translate(left + 2, bottom - text_height)
            cr.scale(text_scale, text_scale)
            cr.set_source_rgba(fore_color[0], fore_color[1], fore_color[2], alpha)
            PangoCairo.update_layout(cr, layout)
            PangoCairo.show_layout(cr, layout)

            cr.restore()
            PangoCairo.update_layout(cr, layout)

    def render_badges(self, cr, widget, surface, media_area, game_item: GameItem | None):
        self.render_platforms(cr, widget, surface, 0, media_area, game_item.platform if game_item else None)

        game_id = game_item.id if game_item else None
        if game_id:
            if self.service:
                game_id = self.service.resolve_game_id(game_id)

            if game_id in MISSING_GAMES.missing_game_ids:
                self.render_text_badge(cr, widget, _("Missing"), 0, media_area.y + media_area.height)

    def draw_media(self, drawing_area: Gtk.DrawingArea, cr, width, height, game_item: GameItem | None):
        if not game_item:
            return
        media_paths = game_item.media_paths or []
        if not media_paths:
            return

        media_path = resolve_media_path(media_paths)
        if not media_path:
            return

        media_width = media_path.width
        media_height = media_path.height
        path = media_path.path
        alpha = 1 if game_item.installed else 100 / 255

        if media_width <= 0 or media_height <= 0 or not path:
            return

        surface = self._get_cached_surface_by_path(drawing_area, path, size=(media_width, media_height))
        if not surface:
            path = get_default_icon_path((media_width, media_height))
            surface = self._get_cached_surface_by_path(
                drawing_area, path, size=(media_width, media_height), preserve_aspect_ratio=False
            )
        if not surface:
            return

        cell_area = Gdk.Rectangle()
        cell_area.x = 0
        cell_area.y = 0
        cell_area.width = width
        cell_area.height = height
        media_area = self.get_media_area(surface, cell_area)
        self.select_badge_metrics(surface, media_width, media_height)

        cr.save()

        inset_fraction = self.get_inset_fraction(game_item.id)
        if inset_fraction > 0:
            media_area.x += (media_area.width * inset_fraction) / 2
            media_area.y += (media_area.height * inset_fraction) / 2
            cr.translate(media_area.x, media_area.y)
            cr.scale(1 - inset_fraction, 1 - inset_fraction)
        else:
            cr.translate(media_area.x, media_area.y)

        media_area.x = 0
        media_area.y = 0

        if alpha >= 1:
            self.render_media(cr, surface, 0, 0)
            if self.show_badges:
                self.render_badges(cr, drawing_area, surface, media_area, game_item)
        else:
            cr.push_group()
            self.render_media(cr, surface, 0, 0)
            if self.show_badges:
                self.render_badges(cr, drawing_area, surface, media_area, game_item)
            cr.pop_group_to_source()
            cr.paint_with_alpha(alpha)
        cr.restore()

        schedule_at_idle(self.cycle_cache)

    def get_preferred_media_size(self, game_item: GameItem | None) -> tuple[int, int]:
        if self.is_library_view() and self.expected_width and self.expected_height:
            return self.expected_width, self.expected_height

        if game_item and game_item.media_paths:
            path = game_item.media_paths[0]
            return path.width, path.height
        return 0, 0


class GameMediaDrawingArea(Gtk.DrawingArea):
    """Drawing area that renders game media using a shared presentation object."""

    def __init__(self, presentation: GameMediaPresentation):
        super().__init__()
        self.presentation = presentation
        self.game_item: GameItem | None = None
        self.set_draw_func(self._draw)
        self.set_content_width(1)
        self.set_content_height(1)

    def set_game_item(self, game_item: GameItem | None) -> None:
        self.game_item = game_item
        width, height = self.presentation.get_preferred_media_size(game_item)
        if width > 0 and height > 0:
            self.set_content_width(width)
            self.set_content_height(height)
        self.queue_draw()

    def _draw(self, drawing_area, cr, width, height):
        self.presentation.draw_media(drawing_area, cr, width, height, self.game_item)


class GameGridCell(Gtk.Box):
    """Grid view cell containing game media and optional title."""

    def __init__(self, presentation: GameMediaPresentation, show_label: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.presentation = presentation
        self.game_item: GameItem | None = None

        self.media_area = GameMediaDrawingArea(presentation)
        self.media_area.set_halign(Gtk.Align.CENTER)
        self.append(self.media_area)

        self.label = Gtk.Label()
        self.label.set_wrap(True)
        self.label.set_wrap_mode(Pango.WrapMode.WORD)
        self.label.set_justify(Gtk.Justification.CENTER)
        self.label.set_halign(Gtk.Align.CENTER)
        self.label.set_valign(Gtk.Align.START)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        if show_label:
            self.append(self.label)
        else:
            self.label.set_visible(False)

    def set_game_item(self, game_item: GameItem | None) -> None:
        self.game_item = game_item
        self.media_area.set_game_item(game_item)
        if game_item:
            self.label.set_markup(game_item.name)
        else:
            self.label.set_text("")

    def set_label_width(self, width: int) -> None:
        self.label.set_size_request(width, -1)

    def clear_label_cache(self) -> None:
        self.label.queue_draw()


class GameListMediaCell(Gtk.Box):
    """List view cell that renders only game media."""

    def __init__(self, presentation: GameMediaPresentation):
        super().__init__()
        self.presentation = presentation
        self.media_area = GameMediaDrawingArea(presentation)
        self.append(self.media_area)

    def set_game_item(self, game_item: GameItem | None) -> None:
        self.media_area.set_game_item(game_item)


def on_media_cache_invalidated() -> None:
    global _MEDIA_CACHE_GENERATION_NUMBER
    _MEDIA_CACHE_GENERATION_NUMBER += 1


from lutris.gui.widgets.utils import MEDIA_CACHE_INVALIDATED  # noqa: E402

MEDIA_CACHE_INVALIDATED.register(on_media_cache_invalidated)
