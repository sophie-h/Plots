import re
from itertools import count
from collections import namedtuple
from gi.repository import GLib, Gtk, Gdk, cairo, Pango, PangoCairo
from enum import Enum

desc = Pango.font_description_from_string("Latin Modern Math 20")
DEBUG = False
dpi = PangoCairo.font_map_get_default().get_resolution()

GREEK_LETTERS = {
    'Alpha': 'Α',
    'Beta': 'Β',
    'Chi': 'Χ',
    'Delta': 'Δ',
    'Epsilon': 'Ε',
    'Eta': 'Η',
    'Gamma': 'Γ',
    'Iota': 'Ι',
    'Kappa': 'Κ',
    'Lambda': 'Λ',
    'Mu': 'Μ',
    'Nu': 'Ν',
    'Omega': 'Ω',
    'Omicron': 'Ο',
    'Phi': 'Φ',
    'Pi': 'Π',
    'Psi': 'Ψ',
    'Rho': 'Ρ',
    'Sigma': 'Σ',
    'Tau': 'Τ',
    'Theta': 'Θ',
    'Upsilon': 'Υ',
    'Xi': 'Ξ',
    'Zeta': 'Ζ',
    'alpha': 'α',
    'beta': 'β',
    'chi': 'χ',
    'delta': 'δ',
    'epsilon': 'ε',
    'eta': 'η',
    'gamma': 'γ',
    'iota': 'ι',
    'kappa': 'κ',
    'lambda': 'λ',
    'mu': 'μ',
    'nu': 'ν',
    'omega': 'ω',
    'omicron': 'ο',
    'phi': 'φ',
    'pi': 'π',
    'psi': 'ψ',
    'rho': 'ρ',
    'sigma': 'σ',
    'tau': 'τ',
    'theta': 'θ',
    'upsilon': 'υ',
    'xi': 'ξ',
    'zeta': 'ζ'
}
GREEK_REGEXES = GREEK_LETTERS.copy()
GREEK_REGEXES['(?<![EUeu])psi'] = GREEK_REGEXES.pop('psi')
FUNCTIONS = ("asinh", "acosh", "atanh", "sinh", "cosh", "tanh", "asin", "acos", "atan", "sin", "cos", "tan", "exp", "log", "ln", "lg")
BINARY_OPERATORS = ("+", "-", "*", "=")

class Editor(Gtk.DrawingArea):
    padding = 4
    def __init__ (self):
        super().__init__()
        self.cursor = Cursor()
        self.test_expr = ElementList([Paren('('), Radical([]), OperatorAtom('sin'), Atom('a'), Paren(')'), Atom('b'), Atom('c'), Expt([Atom('d')]),
             Paren('('),
             Frac([Radical([Frac([Atom('b')], [Atom('c')]), Atom('y')], [Atom('3')])], [Atom('c'), Radical([Atom('a')])]),
             Paren(')')])
        self.expr = ElementList()
        self.cursor.reparent(self.expr, 0)
        self.props.can_focus = True
        self.connect("key-press-event", self.on_key_press)
        self.connect('draw', self.do_draw_cb)
        self.blink_source = None
        self.restart_blink_sequence()

    def do_draw_cb(self, widget, ctx):
        ctx.translate(self.padding, self.padding) # a bit of padding
        scale = 2
        ctx.scale(scale, scale)
        self.expr.compute_metrics(ctx, MetricContext(self.cursor))
        ctx.translate(0, self.expr.ascent)
        self.expr.draw(ctx, self.cursor)
        self.set_size_request(self.expr.width*scale + 2*self.padding,
                              (self.expr.ascent + self.expr.descent)*scale + 2*self.padding)

    def blink_cursor_cb(self):
        self.cursor.visible = not self.cursor.visible
        self.queue_draw()
        return True

    def restart_blink_sequence(self):
        self.cursor.visible = True
        if self.blink_source:
            GLib.source_remove(self.blink_source)
        self.blink_source = GLib.timeout_add(Cursor.BLINK_DELAY, self.blink_cursor_cb)

    def on_key_press(self, widget, event):
        self.restart_blink_sequence()
        if DEBUG:
            print(Gdk.keyval_name(event.keyval))
        char = chr(Gdk.keyval_to_unicode(event.keyval))
        if char.isalnum():
            self.cursor.insert(Atom(char))
            self.queue_draw()
            return
        if char in BINARY_OPERATORS:
            translation = str.maketrans("-*", "−×")
            self.cursor.insert(BinaryOperatorAtom(char.translate(translation)))
            self.queue_draw()
            return
        if char in "!'.":
            translation = str.maketrans("'", "′")
            self.cursor.insert(Atom(char.translate(translation)))
            self.queue_draw()
            return
        if char in "()[]{}":
            self.cursor.insert(Paren(char))
            self.queue_draw()
            return
        if event.keyval == Gdk.KEY_BackSpace:
            self.cursor.backspace(Direction.LEFT)
            self.queue_draw()
            return
        if event.keyval == Gdk.KEY_Delete:
            self.cursor.backspace(Direction.RIGHT)
            self.queue_draw()
            return
        if event.keyval == Gdk.KEY_slash:
            self.cursor.greedy_insert(Frac)
            self.queue_draw()
            return
        if char == "^":
            self.cursor.greedy_insert(Expt)
            self.queue_draw()
            return
        try:
            direction = Direction(event.keyval)
            self.cursor.handle_movement(direction)
            self.queue_draw()
            return
        except ValueError:
            pass

class saved():
    def __init__(self, ctx):
        self.ctx = ctx

    def __enter__(self):
        self.ctx.save()

    def __exit__(self ,exc_type, exc_val, exc_tb):
        self.ctx.restore()
        return False

class MetricContext():
    def __init__(self, cursor=None):
        self.prev = None
        self.paren_stack = []
        self.cursor = cursor

class Cursor():
    WIDTH = 1
    BLINK_DELAY = 600

    def __init__(self):
        self.owner = None
        self.visible = True
        self.pos = 0

    def reparent(self, new_parent, position):
        self.owner = new_parent
        self.pos = position
        if position < 0:
            self.pos = len(self.owner.elements) + position + 1

    def handle_movement(self, direction):
        shift = 0 if direction.displacement() == 1 else -1

        def go_to_parent():
            if self.owner.parent:
                new_list = self.owner.parent.get_next_child(direction, self.owner)
                if new_list is not None:
                    self.owner = new_list
                    self.pos = len(self.owner) if direction.end() == -1 else 0
                else:
                    self.pos = self.owner.parent.index_in_parent + shift + 1
                    self.owner = self.owner.parent.parent

        if direction.vertical():
            go_to_parent()
            return
        adj_idx = self.pos + shift
        try:
            if adj_idx < 0:
                raise IndexError
            adj = self.owner.elements[adj_idx]
            child_list = adj.get_next_child(direction)
            if child_list is not None:
                self.owner = child_list
                self.pos = len(self.owner) if direction.end() == -1 else 0
            else:
                new_pos = self.pos + direction.displacement()
                if new_pos in range(len(self.owner.elements) + 1):
                    self.pos = new_pos
        except IndexError:
            go_to_parent()

    def backspace(self, direction):
        self.owner.backspace(self, direction=direction)

    def insert(self, element):
        self.owner.insert(element, self)

    def greedy_insert(self, cls):
        self.owner.greedy_insert(cls, self)

def italify_string(s):
    def italify_char(c):
        if c == 'h':
            return 'ℎ'
        # lowercase latin
        if c.islower() and c.isascii():
            return chr(ord(c) - 0x61 + 0x1d44e)
        # uppercase latin
        if c.isupper() and c.isascii():
            return chr(ord(c) - 0x41 + 0x1d434)
        # lowercase greek (n.b. don't italify uppers)
        if 0x3b1 <= ord(c) < 0x3b1 + 18:
            return chr(ord(c) - 0x3b1 + 0x1d6fc)
        return c
    return "".join(italify_char(c) for c in s)

def deitalify_char(c):
    if c == 'ℎ':
        return 'h'
    if 0x1d44e <= ord(c) < 0x1d44e + 26:
        return chr(ord(c) - 0x1d44e + 0x61)
    if 0x1d434 <= ord(c) < 0x1d434 + 26:
        return chr(ord(c) - 0x1d434 + 0x41)
    return c

def deitalify_string(s):
    return "".join(deitalify_char(c) for c in s)

class Direction(Enum):
    UP = Gdk.KEY_Up
    DOWN = Gdk.KEY_Down
    LEFT = Gdk.KEY_Left
    RIGHT = Gdk.KEY_Right
    NONE = 0

    def displacement(self):
        if self is self.UP or self is self.LEFT:
            return -1
        elif self is self.DOWN or self is self.RIGHT:
            return 1
        else:
            return 0

    def end(self):
        return -1 if self.displacement() == -1 else 0

    def vertical(self):
        if self is self.UP or self is self.DOWN:
            return True
        else:
            return False

    def horizontal(self):
        return not self.vertical()

class Element():
    """Abstract class describing an element of an equation.

    Implementations must provide parent, index_in_parent, lists, ascent, descent,
    and width properties, compute_metrics(ctx, metric_ctx) and draw(ctx, cursor)."""

    h_spacing = 2

    def __init__(self, parent):
        self.parent = parent
        self.index_in_parent = None
        self.lists = []

    def font_metrics(self, ctx):
        text = Text("x", ctx)
        return text

    def compute_metrics(self, ctx, metric_ctx):
        """To be run at the end of overriding methods, if they
        wish to have parens scale around them"""
        stack = metric_ctx.paren_stack
        if stack:
            stack[-1].ascent = max(self.ascent, stack[-1].ascent)
            stack[-1].descent = max(self.descent, stack[-1].descent)
            stack[-1].compute_stretch()

    def draw(self, ctx, cursor):
        if DEBUG:
            ctx.set_line_width(0.5)
            ctx.set_source_rgba(1, 0, 1 if cursor.owner is self else 0, 0.6)
            ctx.rectangle(0, -self.ascent, self.width, self.ascent + self.descent)
            ctx.stroke()
        ctx.set_source_rgba(0,0,0)
        ctx.move_to(0,0)

    def get_next_child(self, direction, previous=None):
        try:
            previous_idx = self.lists.index(previous)
            new_idx = previous_idx + direction.displacement()
            if new_idx in range(len(self.lists)):
                return self.lists[new_idx]
            else:
                return None
        except ValueError:
            child_idx = -1 if direction.displacement() == -1 else 0
            if self.lists:
                return self.lists[child_idx]
            else:
                return None


class ElementList(Element):
    def __init__(self, elements=None, parent=None):
        super().__init__(parent)
        self.elements = elements or []
        for i, e in enumerate(self.elements):
            e.parent = self
            e.index_in_parent = i

    def __len__(self):
        return len(self.elements)

    def compute_metrics(self, ctx, metric_ctx):
        self.ascent = self.descent = self.width = 0
        metric_ctx = MetricContext(metric_ctx.cursor)
        metric_ctx.prev = self.font_metrics(ctx)
        for i, e in enumerate(self.elements):
            e.index_in_parent = i
            e.compute_metrics(ctx, metric_ctx)
            self.ascent = max(self.ascent, e.ascent)
            self.descent = max(self.descent, e.descent)
            self.width += e.width + 2*e.h_spacing
            metric_ctx.prev = e
        if not self.elements:
            self.ascent = self.font_metrics(ctx).ascent
            self.descent = self.font_metrics(ctx).descent
            self.width = self.font_metrics(ctx).width

    def draw_cursor(self, ctx, ascent, descent, cursor):
        if cursor.owner is self and cursor.visible:
            ctx.set_source_rgb(0, 0, 0)
            ctx.set_line_width(max(ctx.device_to_user_distance(Cursor.WIDTH, Cursor.WIDTH)))
            ctx.move_to(0, descent-2)
            ctx.line_to(0, -ascent+2)
            ctx.move_to(0, 0)
            ctx.stroke()

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        with saved(ctx):
            for i, e in enumerate(self.elements):
                ctx.move_to(0,0)
                if i == cursor.pos:
                    ascent, descent = e.ascent, e.descent
                    if cursor.pos > 0:
                        ascent = max(ascent, self.elements[i-1].ascent)
                        descent = max(descent, self.elements[i-1].descent)
                    self.draw_cursor(ctx, ascent, descent, cursor)
                ctx.move_to(0, 0)
                ctx.translate(e.h_spacing, 0)
                with saved(ctx):
                    e.draw(ctx, cursor)
                ctx.move_to(0,0)
                ctx.translate(e.width + e.h_spacing, 0)
            if cursor.pos == len(self.elements) > 0:
                self.draw_cursor(ctx, self.elements[-1].ascent, self.elements[-1].descent, cursor)
            elif not self.elements:
                self.draw_cursor(ctx, self.ascent, self.descent, cursor)

    def backspace(self, cursor, caller=None, direction=Direction.LEFT):
        if self is not cursor.owner:
            cursor.reparent(self, direction.end())
        if direction is Direction.LEFT:
            shift = -1
        elif direction is Direction.RIGHT:
            shift = 0
        if cursor.pos + shift in range(len(self.elements)):
            target = self.elements[cursor.pos + shift]
            child = target.get_next_child(direction)
            if child is not None:
                cursor.reparent(child, direction.end())
                child.backspace(cursor, direction=direction)
            else:
                cursor.pos += shift
                del self.elements[cursor.pos]
        elif self.parent:
            self.dissolve_parent(cursor)

    def dissolve_parent(self, cursor):
        concatenation = []
        cursor_offset = 0
        for elementlist in self.parent.lists:
            if elementlist is self:
                cursor_offset = len(concatenation)
            concatenation.extend(elementlist.elements)
        self.parent.parent.replace(self.parent, ElementList(concatenation), cursor, cursor_offset)

    def replace(self, old, new, cursor, cursor_offset=0):
        if old.parent is self:
            if isinstance(new, ElementList):
                self.elements[old.index_in_parent:old.index_in_parent+1] = new.elements
                for i, e in enumerate(new.elements):
                    e.parent = self
                    e.index_in_parent = old.index_in_parent + i
                if cursor_offset is not None:
                    cursor.reparent(self, old.index_in_parent + cursor_offset)
            else:
                self.elements[old.index_in_parent] = new
                new.parent = self

    def insert(self, element, cursor):
        self.elements.insert(cursor.pos, element)
        cursor.pos += 1
        element.parent = self
        self.convert_specials(cursor)

    def greedy_insert(self, cls, cursor):
        if cursor.pos > 0 and cls.greedy_insert_left and isinstance(self.elements[cursor.pos-1], (Paren, Atom, Expt)):
            paren_level = 0
            for n, e in enumerate(self.elements[cursor.pos-1::-1]):
                if isinstance(e, Paren):
                    if e.left:
                        paren_level -= 1
                    else:
                        paren_level += 1
                if isinstance(e, Expt):
                    continue
                if paren_level <= 0:
                    break
            if paren_level < 0:
                left = []
            else:
                n += 1
                left = self.elements[cursor.pos - n:cursor.pos]
                del self.elements[cursor.pos - n:cursor.pos]
                cursor.pos -= n
        else:
            left = []
        if cursor.pos < len(self.elements) and cls.greedy_insert_right and isinstance(self.elements[cursor.pos], (Paren, Atom, Expt)):
            paren_level = 0
            for n, e in enumerate(self.elements[cursor.pos:]):
                if isinstance(e, Paren):
                    if e.left:
                        paren_level += 1
                    else:
                        paren_level -= 1
                if isinstance(e, Expt):
                    continue
                if paren_level <= 0:
                    break
            if paren_level < 0:
                right = []
            else:
                n += 1
                right = self.elements[cursor.pos:cursor.pos + n]
                del self.elements[cursor.pos:cursor.pos + n]
        else:
            right = []
        new = cls.make_greedily(left, right)
        self.insert(new, cursor)
        cursor.reparent(new.get_next_child(Direction.LEFT), 0)

    def atoms_at_cursor(self, cursor):
        l = cursor.pos
        while l - 1 >= 0:
            if isinstance(self.elements[l-1], BaseAtom):
                l -= 1
            else:
                break
        r = cursor.pos
        while r < len(self.elements):
            if isinstance(self.elements[r], BaseAtom):
                r += 1
            else:
                break
        return l, r

    @staticmethod
    def atoms_to_string(atoms):
        return "".join(deitalify_string(atom.name) for atom in atoms)

    def convert_specials(self, cursor):
        l, r = self.atoms_at_cursor(cursor)
        atoms = self.elements[l:r]
        names = string_to_names(self.atoms_to_string(atoms))

        # find index of first difference - it will be stored in i
        for i, name, atom in zip(count(), names, atoms):
            if name != deitalify_string(atom.name):
                break
        else:
            return

        new_elems = [name_to_element(name) for name in names]
        self.elements[l:r] = new_elems
        for j, elem in enumerate(new_elems):
            elem.parent = self
            elem.index_in_parent = l + j
        cursor.reparent(self, new_elems[i].index_in_parent)
        cursor.handle_movement(Direction.RIGHT)

def string_to_names(string):
    regex = r"sqrt|."
    regex = "|".join(GREEK_REGEXES) + "|" + "|".join(FUNCTIONS) + "|" + regex
    names = re.findall(regex, string)
    return names

def name_to_element(name):
    if name == 'sqrt':
        return Radical([])
    elif name in FUNCTIONS:
        return OperatorAtom(name)
    elif name in BINARY_OPERATORS:
        return BinaryOperatorAtom(name)
    elif len(name) == 1:
        return Atom(name)
    elif name in GREEK_LETTERS:
        return Atom(GREEK_LETTERS[name])
    else:
        return OperatorAtom(name)

class Text:
    def __init__(self, text, ctx):
        self.layout = PangoCairo.create_layout(ctx)
        self.layout.set_text(text)
        self.layout.set_font_description(desc)
        self.width, self.height = self.layout.get_pixel_size()
        self.ascent = self.layout.get_baseline()/Pango.SCALE
        self.descent = self.height - self.ascent

        # Have to do this because get_pixel_extents returns integer pixels,
        # which are not precise enough
        self.ink_rect, self.logical_rect = self.layout.get_extents()
        for attr in ("x", "y", "width", "height"):
            setattr(self.ink_rect, attr, getattr(self.ink_rect, attr)/Pango.SCALE)
            setattr(self.logical_rect, attr, getattr(self.logical_rect, attr)/Pango.SCALE)

    def draw_at_baseline(self, ctx):
        ctx.move_to(0, -self.ascent)
        PangoCairo.show_layout(ctx, self.layout)

    def draw(self, ctx):
        self.update()
        PangoCairo.show_layout(ctx, self.layout)

    def update(self):
        self.layout.context_changed()

class BaseAtom(Element):
    wants_cursor = False
    h_spacing = 0

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name

    def compute_metrics(self, ctx, metric_ctx):
        self.layout = Text(self.name, ctx)
        self.width, self.ascent, self.descent = self.layout.width, self.layout.ascent, self.layout.descent
        super().compute_metrics(ctx, metric_ctx)

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        self.layout.draw_at_baseline(ctx)

class Atom(BaseAtom):
    def __init__(self, name, parent=None):
        super().__init__(italify_string(name), parent=parent)

    def __repr__(self):
        return "Atom({!r})".format(self.name)

class BinaryOperatorAtom(BaseAtom):
    def __init__(self, name, parent=None):
        super().__init__(name, parent=parent)
        if name == "=":
            self.h_spacing = 6
        else:
            self.h_spacing = 4

class OperatorAtom(BaseAtom):
    h_spacing = 2

    @classmethod
    def any_in_string(cls, string):
        for name in cls.allowed_names:
            i = string.find(name)
            if i != -1:
                return name, i

class Expt(Element):
    greedy_insert_right = True
    greedy_insert_left = False
    h_spacing = 0
    exponent_scale = 0.7

    def __init__(self, exponent=None, parent=None):
        super().__init__(parent)
        self.exponent = ElementList(exponent, self)
        self.lists = [self.exponent]

    def compute_metrics(self, ctx, metric_ctx):
        self.exponent.compute_metrics(ctx, metric_ctx)
        self.child_shift = -self.exponent.descent*self.exponent_scale - metric_ctx.prev.ascent + 14 # -ve y is up
        self.width = self.exponent.width*self.exponent_scale
        self.ascent = self.exponent.ascent*self.exponent_scale - self.child_shift
        self.descent = max(0, metric_ctx.prev.descent,
                           self.exponent.descent*self.exponent_scale + self.child_shift)
        super().compute_metrics(ctx, metric_ctx)

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        with saved(ctx):
            ctx.translate(0, self.child_shift)
            ctx.scale(self.exponent_scale, self.exponent_scale)
            self.exponent.draw(ctx, cursor)

    @classmethod
    def make_greedily(cls, left, right):
        return cls(exponent=right)

class Frac(Element):
    vertical_separation = 4
    greedy_insert_right = greedy_insert_left = True

    def __init__(self, numerator=None, denominator=None, parent=None):
        super().__init__(parent)
        self.numerator = ElementList(numerator, self)
        self.denominator = ElementList(denominator, self)
        self.lists = [self.numerator, self.denominator]

    def compute_metrics(self, ctx, metric_ctx):
        self.numerator.compute_metrics(ctx, metric_ctx)
        self.denominator.compute_metrics(ctx, metric_ctx)
        self.width = max(self.numerator.width, self.denominator.width)

        font_ascent = self.font_metrics(ctx).ascent
        self.bar_height = font_ascent * 0.3
        self.ascent = self.numerator.ascent + self.numerator.descent + \
            self.bar_height + self.vertical_separation//2
        self.descent = self.denominator.ascent + self.denominator.descent + \
            self.vertical_separation//2 - self.bar_height
        super().compute_metrics(ctx, metric_ctx)

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        with saved(ctx):
            ctx.translate(0, -self.bar_height)
            ctx.move_to(0,0)
            ctx.set_line_width(1)
            ctx.line_to(self.width, 0)
            ctx.stroke()
            ctx.move_to(0,0)
            with saved(ctx):
                ctx.translate(self.width//2 - self.numerator.width//2,
                              -self.vertical_separation//2 - self.numerator.descent)
                self.numerator.draw(ctx, cursor)
            with saved(ctx):
                ctx.translate(self.width//2 - self.denominator.width//2,
                              self.vertical_separation//2 + self.denominator.ascent)
                self.denominator.draw(ctx, cursor)

    @classmethod
    def make_greedily(cls, left, right):
        return cls(numerator=left, denominator=right)

class Radical(Element):
    def __init__(self, radicand, index=None, parent=None):
        super().__init__(parent)
        self.radicand = ElementList(radicand, self)
        self.index = ElementList(index, self)
        self.overline_space = 4
        self.lists = [self.radicand]

    def compute_metrics(self, ctx, metric_ctx):
        self.radicand.compute_metrics(ctx, metric_ctx)
        self.index.compute_metrics(ctx, metric_ctx)
        self.symbol = PangoCairo.create_layout(ctx)
        self.symbol.set_text("√")
        self.symbol.set_font_description(desc)
        self.width = self.radicand.width + self.symbol.get_pixel_size().width
        self.ascent = max(self.symbol.get_baseline()//Pango.SCALE,
                          self.radicand.ascent + self.overline_space)
        self.descent = self.radicand.descent
        super().compute_metrics(ctx, metric_ctx)

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        extents = self.symbol.get_pixel_extents()
        symbol_size = extents.ink_rect.height
        scale_factor = max(1, (self.ascent + self.descent)/symbol_size)
        with saved(ctx):
            ctx.translate(0, -self.ascent)
            ctx.scale(1, scale_factor)
            ctx.translate(0, -extents.ink_rect.y)
            ctx.move_to(0, 0)
            PangoCairo.show_layout(ctx, self.symbol)

        ctx.translate(self.symbol.get_pixel_size().width, 0)
        ctx.set_source_rgb(0,0,0)
        ctx.set_line_width(1)
        ctx.move_to(0, -self.ascent + ctx.get_line_width())
        ctx.rel_line_to(self.radicand.width, 0)
        ctx.stroke()
        ctx.move_to(0,0)
        self.radicand.draw(ctx, cursor)

class Paren(Element):
    wants_cursor = False
    h_spacing = 0
    shrink = 0.7

    def __init__(self, char, parent=None):
        super().__init__(parent)
        if len(char) != 1:
            raise ValueError("{!r} is not a valid paren".format(char))
        if char in "({[":
            self.left = True
        elif char in "]})":
            self.left = False
        else:
            raise ValueError("{!r} is not a valid paren".format(char))
        self.char = char
        self.match = None

    def compute_metrics(self, ctx, metric_ctx):
        self.text = Text(self.char, ctx)
        if self.char == "[":
            self.top, self.mid, self.bot = [Text(c, ctx) for c in "⎡⎢⎣"]
        elif self.char == "]":
            self.top, self.mid, self.bot = [Text(c, ctx) for c in "⎤⎥⎦"]

        self.width, self.ascent, self.descent = self.text.width, self.text.ascent, self.text.descent

        if self.left:
            metric_ctx.paren_stack.append(self)
        else:
            if metric_ctx.paren_stack:
                self.match = metric_ctx.paren_stack.pop()
            else:
                self.match = metric_ctx.prev
            self.ascent = self.match.ascent
            self.descent = self.match.descent
            super().compute_metrics(ctx, metric_ctx)
        self.compute_stretch()

    def compute_stretch(self):
        self.scale_factor = max(1, (self.ascent + self.descent)/self.text.ink_rect.height)
        if self.scale_factor > 1.5 and self.char in "[]":
            self.stretch = True
            self.scale_factor = max(1, (self.ascent + self.descent)/self.mid.height)
            self.width = self.mid.width*self.shrink
            self.h_spacing = 0
            if isinstance(self.match, Paren) and self.match.char in "[]":
                self.match.stretch = True
                self.match.scale_factor = self.scale_factor
                self.match.width = self.width
                self.match.h_spacing = self.h_spacing
        else:
            self.stretch = False

    def draw(self, ctx, cursor):
        super().draw(ctx, cursor)
        if self.stretch:
            with saved(ctx):
                ctx.translate(0, -self.ascent - self.top.ink_rect.y*self.shrink)
                ctx.move_to(0,0)
                ctx.scale(self.shrink,self.shrink)
                self.top.draw(ctx)
            with saved(ctx):
                ctx.translate(0, self.descent)
                ctx.move_to(0,0)
                ctx.scale(self.shrink,self.shrink)
                ctx.translate(0, -self.bot.ink_rect.y - self.bot.ink_rect.height)
                ctx.move_to(0,0)
                self.bot.draw(ctx)
            with saved(ctx):
                scale_factor = max(1, (self.ascent + self.descent)/self.mid.ink_rect.height)
                ctx.translate(0, -self.ascent)
                ctx.scale(1, self.scale_factor)
                ctx.translate(0, -self.mid.ink_rect.y)
                ctx.scale(self.shrink,1)
                ctx.move_to(0, 0)
                self.mid.draw(ctx)
        else:
            with saved(ctx):
                ctx.scale(1, self.scale_factor)
                ctx.translate(0, -self.ascent/self.scale_factor-self.text.ink_rect.y)
                ctx.move_to(0, 0)
                self.text.draw(ctx)
