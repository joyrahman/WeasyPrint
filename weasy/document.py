# coding: utf8

#  WeasyPrint converts web documents (HTML, CSS, ...) to PDF.
#  Copyright (C) 2011  Simon Sapin
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.


import math
import StringIO

import lxml.html
import cairo

from .css import get_all_computed_styles
from .css.utils import HTML4_DEFAULT_STYLESHEET
from .css.computed_values import LENGTHS_TO_PIXELS
from .formatting_structure.build import build_formatting_structure
from .layout import layout
from . import draw


DEFAULT_USER_AGENT_STYLESHEETS = (HTML4_DEFAULT_STYLESHEET,)


class Document(object):
    def __init__(self, dom, user_stylesheets=None,
                 user_agent_stylesheets=DEFAULT_USER_AGENT_STYLESHEETS):
        assert getattr(dom, 'tag', None) == 'html', (
            'HTML document expected, got %r.' % (dom,))

        self.user_stylesheets = user_stylesheets or []
        self.user_agent_stylesheets = user_agent_stylesheets or []

        #: lxml HtmlElement object
        self.dom = dom

        self._computed_styles = None
        self._formatting_structure = None
        self._pages = None

    @classmethod
    def from_string(cls, source, **kwargs):
        """
        Make a document from an HTML string.
        """
        return cls(lxml.html.document_fromstring(source), **kwargs)

    @classmethod
    def from_file(cls, file_or_filename_or_url, **kwargs):
        """
        Make a document from a filename or open file object.
        """
        root_element = lxml.html.parse(file_or_filename_or_url).getroot()
        return cls(root_element, **kwargs)

    def style_for(self, element, pseudo_type=None):
        """
        Convenience method to get the computed styles for an element.
        """
        return self.computed_styles[(element, pseudo_type)]

    @property
    def computed_styles(self):
        """
        dict of (element, pseudo_element_type) -> StyleDict
        StyleDict: a dict of property_name -> PropertyValue,
                   also with attribute access
        """
        if self._computed_styles is None:
            self._computed_styles = get_all_computed_styles(
                self,
                user_stylesheets=self.user_stylesheets,
                ua_stylesheets=self.user_agent_stylesheets,
                medium='print')
        return self._computed_styles

    @property
    def formatting_structure(self):
        """
        The Box object for the root element. Represents the tree of all boxes.
        """
        if self._formatting_structure is None:
            self._formatting_structure = build_formatting_structure(self)
        return self._formatting_structure

    @property
    def pages(self):
        """
        List of layed-out pages with an absolute size and postition
        for every box.
        """
        if self._pages is None:
            self._pages = layout(self)
        return self._pages


class PNGDocument(Document):
    def __init__(self, dom):
        super(PNGDocument, self).__init__(dom)
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)

    def draw_page(self, page):
        """Draw a single page and return an ImageSurface."""
        width = int(math.ceil(page.outer_width))
        height = int(math.ceil(page.outer_height))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = draw.CairoContext(surface)
        draw.draw_page(page, context)
        self.surface.finish()
        return width, height, surface

    def write_page_to(self, page_index, target):
        """Write a single page as PNG into a file-like or filename `target`."""
        width, height, surface = self.draw_page(self.pages[page_index])
        surface.write_to_png(target)

    def write_to(self, target):
        """Write all pages as PNG into a file-like or filename `target`.

        Pages are layed out vertically each above the next and centered
        horizontally.
        """
        pages = [self.draw_page(page) for page in self.pages]
        total_height = sum(height for width, height, surface in pages)
        max_width = max(width for width, height, surface in pages)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,
            max_width, total_height)
        context = draw.CairoContext(surface)

        position_y = 0
        for width, height, page_surface in pages:
            position_x = (max_width - width) // 2
            with context.stacked():
                context.translate(position_x, position_y)
                context.set_source(cairo.SurfacePattern(page_surface))
                context.paint()
            position_y += height

        surface.write_to_png(target)


class PDFDocument(Document):
    def __init__(self, dom):
        super(PDFDocument, self).__init__(dom)
        # Use a dummy page size initially
        self.surface = cairo.PDFSurface(None, 1, 1)

    def write_to(self, target):
        """
        Write the whole document as PDF into a file-like or filename `target`.
        """
        # The actual page size is set for each page.
        surface = cairo.PDFSurface(target, 1, 1)

        px_to_pt = 1 / LENGTHS_TO_PIXELS['pt']
        for page in self.pages:
            # Actual page size is here. May be different between pages.
            surface.set_size(
                page.outer_width * px_to_pt,
                page.outer_height * px_to_pt)
            context = draw.CairoContext(surface)
            context.scale(px_to_pt, px_to_pt)
            draw.draw_page(page, context)
            surface.show_page()

        surface.finish()