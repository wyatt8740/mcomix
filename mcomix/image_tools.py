"""image_tools.py - Various image manipulations."""

import operator
from gi.repository import GLib, GdkPixbuf, Gdk, Gtk
import PIL
import jxlpy
import jxlpy.JXLImagePlugin
from PIL import Image
from PIL import ImageCms
from PIL import ImageEnhance
from PIL import ImageOps
from io import StringIO, BytesIO

from mcomix.preferences import prefs
from mcomix import constants
from mcomix import log
from mcomix import tools

import base64

# from pathlib import Path # to check if files exist

PIL_VERSION = ('Pillow', PIL.__version__)

# Unfortunately gdk_pixbuf_version is not exported, so show the GTK+ version instead.
log.info('GDK version: %s, GTK+: %s.%s', GdkPixbuf.PIXBUF_VERSION, Gtk.get_major_version(), Gtk.get_minor_version())
log.info('PIL version: %s [%s]', PIL_VERSION[0], PIL_VERSION[1])

# Fallback pixbuf for missing images.
MISSING_IMAGE_ICON = None

_missing_icon_dialog = Gtk.Dialog()
_missing_icon_pixbuf = _missing_icon_dialog.render_icon(
        Gtk.STOCK_MISSING_IMAGE, Gtk.IconSize.LARGE_TOOLBAR)
MISSING_IMAGE_ICON = _missing_icon_pixbuf
assert MISSING_IMAGE_ICON

GTK_GDK_COLOR_BLACK = Gdk.color_parse('black')
GTK_GDK_COLOR_WHITE = Gdk.color_parse('white')

# kill zip bomb warnings from PIL
Image.MAX_IMAGE_PIXELS = None


# to test if profile has been changed and matrices need updated
cur_profile_name = prefs['color managed display icc profile']
cur_render_intent = prefs['managed color rendering intent']
# transformations for bog standard rgb images with no built-in profile
# information. These can be re-used until the profile name is changed.

# pre-built 'thunks' to massively accelerate correction calculations on
# images that don't have embedded colour profiles (assumes they are sRGB,
# similarly to how Firefox now does):
default_srgb_profile = ImageCms.createProfile("sRGB", -1)
dest_profile = prefs['color managed display icc profile']
if not dest_profile:
    dest_profile=default_srgb_profile
default_srgb_rgba_xform = ImageCms.buildTransform(
            default_srgb_profile,
            dest_profile,
            'RGBA', 'RGBA',
            prefs['managed color rendering intent']
        )
default_srgb_rgb_xform = None
default_srgb_rgb_xform = ImageCms.buildTransform(
            default_srgb_profile,
            dest_profile,
            'RGB', 'RGB',
            prefs['managed color rendering intent']
        )

def update_xforms():
    global cur_profile_name
    global cur_render_intent
    global default_srgb_profile
    global default_srgb_rgba_xform
    global default_srgb_rgb_xform
    if bool(prefs['color management enabled']):
        dest_profile=prefs['color managed display icc profile'] if prefs['color managed display icc profile'] else default_srgb_profile
        if (cur_profile_name != prefs['color managed display icc profile'] or cur_render_intent != prefs['managed color rendering intent']):
            default_srgb_rgba_xform = ImageCms.buildTransform(
                default_srgb_profile,
                dest_profile,
                'RGBA', 'RGBA',
                prefs['managed color rendering intent']
            )
            default_srgb_rgb_xform = ImageCms.buildTransform(
                default_srgb_profile,
                dest_profile,
                'RGB', 'RGB',
                prefs['managed color rendering intent']
            )
            cur_profile_name = prefs['color managed display icc profile']
            cur_render_intent = prefs['managed color rendering intent']


def rotate_pixbuf(src, rotation):
    rotation %= 360
    if 0 == rotation:
        return src
    if 90 == rotation:
        return src.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
    if 180 == rotation:
        return src.rotate_simple(GdkPixbuf.PixbufRotation.UPSIDEDOWN)
    if 270 == rotation:
        return src.rotate_simple(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)
    raise ValueError("unsupported rotation: %s" % rotation)


def get_fitting_size(source_size, target_size,
                     keep_ratio=True, scale_up=False):
    """ Return a scaled version of <source_size>
    small enough to fit in <target_size>.

    Both <source_size> and <target_size>
    must be (width, height) tuples.

    If <keep_ratio> is True, aspect ratio is kept.

    If <scale_up> is True, <source_size> is scaled up
    when smaller than <target_size>.
    """
    width, height = target_size
    src_width, src_height = source_size
    if not scale_up and src_width <= width and src_height <= height:
        width, height = src_width, src_height
    else:
        if keep_ratio:
            if float(src_width) / width > float(src_height) / height:
                height = int(max(src_height * width / src_width, 1))
            else:
                width = int(max(src_width * height / src_height, 1))
    return (width, height)

def fit_pixbuf_to_rectangle(src, rect, rotation):
    return fit_in_rectangle(src, rect[0], rect[1],
                            rotation=rotation,
                            keep_ratio=False,
                            scale_up=True)

def fit_in_rectangle(src, width, height, keep_ratio=True, scale_up=False, rotation=0, scaling_quality=None, pil_filter=None, is_thumb=False):
    """Scale (and return) a pixbuf so that it fits in a rectangle with
    dimensions <width> x <height>. A negative <width> or <height>
    means an unbounded dimension - both cannot be negative.

    If <rotation> is 90, 180 or 270 we rotate <src> first so that the
    rotated pixbuf is fitted in the rectangle.

    Unless <scale_up> is True we don't stretch images smaller than the
    given rectangle.

    If <keep_ratio> is True, the image ratio is kept, and the result
    dimensions may be smaller than the target dimensions.

    If <pil_filter> is not None, a filter from PIL will be used to
    resample the image.

    If <src> has an alpha channel it gets a checkboard background.
    """
    # "Unbounded" really means "bounded to 100000 px" - for simplicity.
    # MComix would probably choke on larger images anyway.
    if width < 0:
        width = 100000
    elif height < 0:
        height = 100000
    width = max(width, 1)
    height = max(height, 1)

    rotation %= 360
    if rotation not in (0, 90, 180, 270):
        raise ValueError("unsupported rotation: %s" % rotation)
    if rotation in (90, 270):
        width, height = height, width

    if scaling_quality is None:
        scaling_quality = prefs['scaling quality']

    if pil_filter is None:
        pil_filter = prefs['pil scaling filter']

    if prefs['default pixel art mode']:
        # this overrides all other filtering options
        scaling_quality = GdkPixbuf.InterpType.NEAREST
        pil_filter = False

    src_width = src.get_width()
    src_height = src.get_height()

    width, height = get_fitting_size((src_width, src_height),
                                     (width, height),
                                     keep_ratio=keep_ratio,
                                     scale_up=scale_up)

    if src.get_has_alpha():
        if prefs['checkered bg for transparent images']:
            check_size, color1, color2 = 8, 0x777777, 0x999999
        else:
#            check_size, color1, color2 = 1024, 0xFFFFFF, 0xFFFFFF
# wyatt: transparency should be background colour as set in prefs instead of hardcoded white
#            check_size, color1, color2 = 1024, 0xFFFFFF, 0xFFFFFF
            # convert the floating point decimal format colour list to a
            # hexadecimal colour code. Uses bitwise shifting and bitwise OR.
            r,g,b,a = [int(p*255) for p in prefs['bg colour']]
# hack
# targetted 0a0a0a, got 0b0b0b. good enough
#            if bool(prefs['color management enabled']):
#                bgcol = 5<<16 | 3<<8 | 8 # hex(r<<16 | g<<8 | b)
#            else:
            bgcol = r<<16 | g<<8 | b # hex(r<<16 | g<<8 | b)
            check_size, color1, color2 = 1024, bgcol, bgcol
        if width == src_width and height == src_height:
            # Using anything other than nearest interpolation will result in a
            # modified image if no resizing takes place (even if it's opaque).
            scaling_quality = GdkPixbuf.InterpType.NEAREST
#        src = src.composite_color_simple(width, height, scaling_quality,
#                                         255, check_size, color1, color2)

            src = src.composite_color_simple(width, height, scaling_quality,
                                             255, check_size, color1, color2)
        elif pil_filter == -1: # scale; use GDK PixBuf only
            src = src.composite_color_simple(width, height, scaling_quality,
                                             255, check_size, color1, color2)
        else:
            # use PIL filter and then composite. Since PIL already resized,
            # use NEAREST for the composition step.
            src = pil_to_pixbuf(pixbuf_to_pil(src).resize(
                [width,height], resample=pil_filter)).composite_color_simple(
                    width, height, GdkPixbuf.InterpType.NEAREST, 255,
                    check_size, color1, color2)

#   elif width != src_width or height != src_height:
#       src = src.scale_simple(width, height, scaling_quality)
    elif width != src_width or height != src_height: # opaque and needs resized
        if pil_filter == -1:
            src = src.scale_simple(width, height, scaling_quality)
        else:
            src = pil_to_pixbuf(
                pixbuf_to_pil(src).resize([width,height],resample=pil_filter))
    src = rotate_pixbuf(src, rotation)

    ################ 3D LUT CODE #######################

    im = pixbuf_to_pil(src)
    if not is_thumb:
        if bool(prefs['color management enabled']) and bool(prefs['color managed display icc profile']):
            if im.info.get('icc_profile') is None:
                # Fall back on sRGB if no profile is embedded. Either RGB or RGBA mode.
                # (images will be converted to fit).
                icc_in = default_srgb_profile
            else:
                # icc_in = BytesIO(im.info.get('icc_profile'))
                icc_in = PIL._imagingcms.profile_frombytes(im.info.get('icc_profile'))
                # handles indexed / black and white, and grayscale images
                # this function's source currently does nothing if source and destination match.
            im=im.convert('RGBA' if src.get_has_alpha() else 'RGB') # chooses RGB or RGBA appropriately
                # im=im.convert('RGB' if src.get_has_alpha() else 'RGBA')

            if icc_in == default_srgb_profile:
                # do any necessary transform regenerations based on pref changes
                update_xforms()
                color_xform = default_srgb_rgba_xform if src.get_has_alpha() else default_srgb_rgb_xform

            # need to apply any color corrections _after_ resize is completed, since
            # the LUT is supposed to be the final step before being drawn on-screen.
            # Unfortunately, this means another pixbuf -> pil -> pixbuf transform.
            # create a transform

            # (NOTE: maybe there should be a global one for sRGB, since it's so
            # common, just to avoid having to regenerate the conversion  matrix it
            # on every image.
            if icc_in != default_srgb_profile:
                try:
                    color_xform = ImageCms.buildTransform(icc_in,
                            prefs['color managed display icc profile'],
                            im.mode, im.mode,
                            prefs['managed color rendering intent'])
                except PIL.ImageCms.PyCMSError:
                    color_xform = default_srgb_rgba_xform if src.get_has_alpha() else default_srgb_rgb_xform

            ImageCms.applyTransform(im, color_xform, inPlace=True)

    src = pil_to_pixbuf(im)

    ############### END 3D LUT CODE ####################

    return src


def add_border(pixbuf, thickness, colour=0x000000FF):
    """Return a pixbuf from <pixbuf> with a <thickness> px border of
    <colour> added.
    """
    canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
        pixbuf.get_width() + thickness * 2,
        pixbuf.get_height() + thickness * 2)
    canvas.fill(colour)
    pixbuf.copy_area(0, 0, pixbuf.get_width(), pixbuf.get_height(),
        canvas, thickness, thickness)
    return canvas


def get_most_common_edge_colour(pixbufs, edge=2):
    """Return the most commonly occurring pixel value along the four edges
    of <pixbuf>. The return value is a sequence, (r, g, b), with 16 bit
    values. If <pixbuf> is a tuple, the edges will be computed from
    both the left and the right image.

    Note: This could be done more cleanly with subpixbuf(), but that
    doesn't work as expected together with get_pixels().
    """

    def group_colors(colors, steps=10):
        """ This rounds a list of colors in C{colors} to the next nearest value,
        i.e. 128, 83, 10 becomes 130, 85, 10 with C{steps}=5. This compensates for
        dirty colors where no clear dominating color can be made out.

        @return: The color that appears most often in the prominent group."""

        # Start group
        group = (0, 0, 0)
        # List of (count, color) pairs, group contains most colors
        colors_in_prominent_group = []
        color_count_in_prominent_group = 0
        # List of (count, color) pairs, current color group
        colors_in_group = []
        color_count_in_group = 0

        for count, color in colors:

            # Round color
            rounded = [0] * len(color)
            for i, color_value in enumerate(color):
                if steps % 2 == 0:
                    middle = steps // 2
                else:
                    middle = steps // 2 + 1

                remainder = color_value % steps
                if remainder >= middle:
                    color_value = color_value + (steps - remainder)
                else:
                    color_value = color_value - remainder

                rounded[i] = min(255, max(0, color_value))

            # Change prominent group if necessary
            if rounded == group:
                # Color still fits in the previous color group
                colors_in_group.append((count, color))
                color_count_in_group += count
            else:
                # Color group changed, check if current group has more colors
                # than last group
                if color_count_in_group > color_count_in_prominent_group:
                    colors_in_prominent_group = colors_in_group
                    color_count_in_prominent_group = color_count_in_group

                group = rounded
                colors_in_group = [ (count, color) ]
                color_count_in_group = count

        # Cleanup if only one edge color group was found
        if color_count_in_group > color_count_in_prominent_group:
            colors_in_prominent_group = colors_in_group

        colors_in_prominent_group.sort(key=operator.itemgetter(0), reverse=True)
        # List is now sorted by color count, first color appears most often
        return colors_in_prominent_group[0][1]

    def get_edge_pixbuf(pixbuf, side, edge):
        """ Returns a pixbuf corresponding to the side passed in <side>.
        Valid sides are 'left', 'right', 'top', 'bottom'. """
        pixbuf = static_image(pixbuf)
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        edge = min(edge, width, height)

        subpix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,
                pixbuf.get_has_alpha(), 8, edge, height)
        if side == 'left':
            pixbuf.copy_area(0, 0, edge, height, subpix, 0, 0)
        elif side == 'right':
            pixbuf.copy_area(width - edge, 0, edge, height, subpix, 0, 0)
        elif side == 'top':
            pixbuf.copy_area(0, 0, width, edge, subpix, 0, 0)
        elif side == 'bottom':
            pixbuf.copy_area(0, height - edge, width, edge, subpix, 0, 0)
        else:
            assert False, 'Invalid edge side'

        return subpix

    if not pixbufs:
        return (0, 0, 0)

    if not isinstance(pixbufs, (tuple, list)):
        left_edge = get_edge_pixbuf(pixbufs, 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs, 'right', edge)
    else:
        assert len(pixbufs) == 2, 'Expected two pages in list'
        left_edge = get_edge_pixbuf(pixbufs[0], 'left', edge)
        right_edge = get_edge_pixbuf(pixbufs[1], 'right', edge)

    # Find all edge colors. Color count is separate for all four edges
    ungrouped_colors = []
    for edge in (left_edge, right_edge):
        im = pixbuf_to_pil(edge)
        ungrouped_colors.extend(im.getcolors(im.size[0] * im.size[1]))

    # Sum up colors from all edges
    ungrouped_colors.sort(key=operator.itemgetter(1))
    most_used = group_colors(ungrouped_colors)[:3]
    return [color * 257 for color in most_used]

def pil_to_pixbuf(im, keep_orientation=False, is_thumb=False):
    """Return a pixbuf created from the PIL <im>."""
    if not is_thumb:
        # if there's an ICC profile, we need to make it into base64 so it can
        # be preserved as pixbuf metadata (which is all strings).
        profile=None
        if im.info.get('icc_profile') is not None:
            profile=base64.b64encode(im.info.get('icc_profile'))

    if im.mode.startswith('RGB'):
        has_alpha = im.mode == 'RGBA'
    elif im.mode in ('LA', 'P'):
        has_alpha = True
    else:
        has_alpha = False
    target_mode = 'RGBA' if has_alpha else 'RGB'
    if im.mode != target_mode:
        im = im.convert(target_mode)
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(im.tobytes()), GdkPixbuf.Colorspace.RGB,
        has_alpha, 8,
        im.size[0], im.size[1],
        (4 if has_alpha else 3) * im.size[0]
    )
    if keep_orientation:
        # Keep orientation metadata.
        orientation = None
        exif = im.getexif()
        orientation = exif.get(274, None)
        if orientation is None:
            # Maybe it's a PNG? Try alternative method.
            orientation = _get_png_implied_rotation(im)
        if orientation is not None:
            setattr(pixbuf, 'orientation', str(orientation))
        if not is_thumb:
            # need to take the ICC profile along for the ride by attaching it to the returned pixbuf.
            if profile is not None:
                setattr(pixbuf, 'icc-profile', str(profile))
    return pixbuf

def pixbuf_to_pil(pixbuf):
    """Return a PIL image created from <pixbuf>."""
    dimensions = pixbuf.get_width(), pixbuf.get_height()
    stride = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    mode = 'RGBA' if pixbuf.get_has_alpha() else 'RGB'
    im = Image.frombuffer(mode, dimensions, pixels, 'raw', mode, stride, 1)
    # make sure ICC profile metadata survives conversion every time
    profile=pixbuf.get_option('icc-profile')
    # print(profile)
    #print('TYPE OF THING IS: ' + str(type(profile)))
    #print(len(profile))
    if profile is not None:
        im.info['icc_profile']=base64.b64decode(profile) # not sure if I can do this, but it's Python, so probably.
    return im

def is_animation(pixbuf):
    return isinstance(pixbuf, GdkPixbuf.PixbufAnimation)

def static_image(pixbuf):
    """ Returns a non-animated version of the specified pixbuf. """
    if is_animation(pixbuf):
        return pixbuf.get_static_image()
    return pixbuf

def unwrap_image(image):
    """ Returns an object that contains the image data based on
    Gtk.Image.get_storage_type or None if image is None or image.get_storage_type
    returns Gtk.IMAGE_EMPTY. """
    if image is None:
        return None
    t = image.get_storage_type()
#    if t == Gtk.IMAGE_EMPTY:
    if t == Gtk.ImageType.EMPTY:
        return None
    if t == Gtk.ImageType.PIXBUF:
        return image.get_pixbuf()
    if t == Gtk.ImageType.ANIMATION:
        return image.get_animation()
    if t == Gtk.ImageType.PIXMAP:
        return image.get_pixmap()
    if t == Gtk.ImageType.IMAGE:
        return image.get_image()
    if t == Gtk.ImageType.STOCK:
        return image.get_stock()
    if t == Gtk.ImageType.ICON_SET:
        return image.get_icon_set()
    raise ValueError()

def set_from_pixbuf(image, pixbuf):
    if is_animation(pixbuf):
        return image.set_from_animation(pixbuf)
    else:
        return image.set_from_pixbuf(pixbuf)

def load_pixbuf(path):
    """ Loads a pixbuf from a given image file. """
    pixbuf = None
    last_error = None
    providers = get_image_info(path)[2]
    for provider in providers:
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                if prefs['animation mode'] != constants.ANIMATION_DISABLED:
                    try:
                        pixbuf = GdkPixbuf.PixbufAnimation.new_from_file(path)
                        if pixbuf.is_static_image():
                            pixbuf = pixbuf.get_static_image()
                    except GLib.GError:
                        # NOTE: Broken JPEGs sometimes result in this exception.
                        # However, one may be able to load them using
                        # Gdk.pixbuf_new_from_file, so we need to continue.
                        pass
                if pixbuf is None:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            elif provider == constants.IMAGEIO_PIL:
                # TODO When using PIL, whether or how animations work is
                # currently undefined.
                im = Image.open(path)
                pixbuf = pil_to_pixbuf(im, keep_orientation=True)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in loading %s", provider, path)
            break
        log.debug("provider %s failed to load %s", provider, path)
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error or TypeError()
    return pixbuf

def load_pixbuf_size(path, width, height, is_thumb=False):
    """ Loads a pixbuf from a given image file and scale it to fit
    inside (width, height). """
    # TODO similar to load_pixbuf, should be merged using callbacks etc.
    pixbuf = None
    last_error = None
    image_format, image_dimensions, providers = get_image_info(path)
    for provider in providers:
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                # If we could not get the image info, still try to load
                # the image to let GdkPixbuf raise the appropriate exception.
                if (0, 0) == image_dimensions:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                # Work around GdkPixbuf bug: https://bugzilla.gnome.org/show_bug.cgi?id=735422
                # (currently https://gitlab.gnome.org/GNOME/gdk-pixbuf/issues/45)
                elif 'GIF' == image_format:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                else:
                    # Don't upscale if smaller than target dimensions!
                    image_width, image_height = image_dimensions
                    if image_width <= width and image_height <= height:
                        width, height = image_width, image_height
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, width, height)
#                   out = GdkPixbuf.Pixbuf.new_from_file_at_size(path, width, height)
#                   del pixbuf
#                   gc.collect()
#                   return out
#               out = fit_in_rectangle(pixbuf, width, height,
#                                 scaling_quality=GdkPixbuf.InterpType.BILINEAR)
#        del pixbuf
#        gc.collect()
#        return out
            elif provider == constants.IMAGEIO_PIL:
                im = Image.open(path)
                im.draft(None, (width, height))
                pixbuf = pil_to_pixbuf(im, keep_orientation=True, is_thumb=is_thumb)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in loading %s at size %s", provider, path, (width, height))
            break
        log.debug("provider %s failed to load %s at size %s", provider, path, (width, height))
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error or TypeError()
    return fit_in_rectangle(pixbuf, width, height, GdkPixbuf.InterpType.BILINEAR, is_thumb=is_thumb)

def load_pixbuf_data(imgdata):
    """ Loads a pixbuf from the data passed in <imgdata>. """
    # TODO similar to load_pixbuf, should be merged using callbacks etc.
    pixbuf = None
    last_error = None
    for provider in (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL):
        try:
            # TODO use dynamic dispatch instead of "if" chain
            if provider == constants.IMAGEIO_GDKPIXBUF:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(imgdata)
                loader.close()
                pixbuf = loader.get_pixbuf()
            elif provider == constants.IMAGEIO_PIL:
                pixbuf = pil_to_pixbuf(Image.open(StringIO(imgdata)), keep_orientation=True)
            else:
                raise TypeError()
        except Exception as e:
            # current provider could not load image
            last_error = e
        if pixbuf is not None:
            # stop loop on success
            log.debug("provider %s succeeded in decoding %s bytes", provider, len(imgdata))
            break
        log.debug("provider %s failed to decode %s bytes", provider, len(imgdata))
    if pixbuf is None:
        # raising necessary because caller expects pixbuf to be not None
        raise last_error
    return pixbuf

def enhance(pixbuf, brightness=1.0, contrast=1.0, saturation=1.0,
  sharpness=1.0, autocontrast=False):
    """Return a modified pixbuf from <pixbuf> where the enhancement operations
    corresponding to each argument has been performed. A value of 1.0 means
    no change. If <autocontrast> is True it overrides the <contrast> value,
    but only if the image mode is supported by ImageOps.autocontrast (i.e.
    it is L or RGB.)
    """
    im = pixbuf_to_pil(pixbuf)
    if brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(brightness)
    if autocontrast and im.mode in ('L', 'RGB'):
        im = ImageOps.autocontrast(im, cutoff=0.1)
    elif contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if saturation != 1.0:
        im = ImageEnhance.Color(im).enhance(saturation)
    if sharpness != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharpness)
    return pil_to_pixbuf(im)

def _get_png_implied_rotation(pixbuf_or_image):
    """Same as <get_implied_rotation> for PNG files.

    Lookup for Exif data in the tEXt chunk.
    """
    if isinstance(pixbuf_or_image, GdkPixbuf.Pixbuf):
        raw_exif = pixbuf_or_image.get_option('tEXt::Raw profile type exif')
    elif isinstance(pixbuf_or_image, Image.Image):
        raw_exif = pixbuf_or_image.info.get('Raw profile type exif')
    else:
        raise ValueError()
    if raw_exif is None:
        return None
    raw_exif = raw_exif.split('\n')
    if len(raw_exif) < 4 or 'exif' != raw_exif[1]:
        # Not valid Exif data.
        return None
    size = int(raw_exif[2])
    try:
        data = bytes.fromhex(''.join(raw_exif[3:]))
    except ValueError:
        # Not valid hexadecimal content.
        return None
    if size != len(data):
        # Sizes should match.
        return None
    exif = Image.Exif()
    exif.load(data)
    orientation = exif.get(274, None) # Orientation tag
    if orientation is not None:
        orientation = str(orientation)
    return orientation

def get_implied_rotation(pixbuf):
    """Return the implied rotation in degrees: 0, 90, 180, or 270.

    The implied rotation is the angle (in degrees) that the raw pixbuf should
    be rotated in order to be displayed "correctly". E.g. a photograph taken
    by a camera that is held sideways might store this fact in its Exif data,
    and the pixbuf loader will set the orientation option correspondingly.
    """
    pixbuf = static_image(pixbuf)
    orientation = getattr(pixbuf, 'orientation', None)
    if orientation is None:
        orientation = pixbuf.get_option('orientation')
    if orientation is None:
        # Maybe it's a PNG? Try alternative method.
        orientation = _get_png_implied_rotation(pixbuf)
    if orientation == '3':
        return 180
    elif orientation == '6':
        return 90
    elif orientation == '8':
        return 270
    return 0


def get_size_rotation(width, height):
    """ Determines the rotation to be applied.
    Returns the degree of rotation (0, 90, 180, 270). """

    size_rotation = 0

    if (height > width and
        prefs['auto rotate depending on size'] in
            (constants.AUTOROTATE_HEIGHT_90, constants.AUTOROTATE_HEIGHT_270)):

        if prefs['auto rotate depending on size'] == constants.AUTOROTATE_HEIGHT_90:
            size_rotation = 90
        else:
            size_rotation = 270
    elif (width > height and
          prefs['auto rotate depending on size'] in
            (constants.AUTOROTATE_WIDTH_90, constants.AUTOROTATE_WIDTH_270)):

        if prefs['auto rotate depending on size'] == constants.AUTOROTATE_WIDTH_90:
            size_rotation = 90
        else:
            size_rotation = 270

    return size_rotation

def combine_pixbufs( pixbuf1, pixbuf2, are_in_manga_mode ):
    if are_in_manga_mode:
        r_source_pixbuf = pixbuf1
        l_source_pixbuf = pixbuf2
    else:
        l_source_pixbuf = pixbuf1
        r_source_pixbuf = pixbuf2

    has_alpha = False

    if l_source_pixbuf.get_property( 'has-alpha' ) or \
       r_source_pixbuf.get_property( 'has-alpha' ):
        has_alpha = True

    bits_per_sample = 8

    l_source_pixbuf_width = l_source_pixbuf.get_property( 'width' )
    r_source_pixbuf_width = r_source_pixbuf.get_property( 'width' )

    l_source_pixbuf_height = l_source_pixbuf.get_property( 'height' )
    r_source_pixbuf_height = r_source_pixbuf.get_property( 'height' )

    new_width = l_source_pixbuf_width + r_source_pixbuf_width

    new_height = max( l_source_pixbuf_height, r_source_pixbuf_height )

    new_pix_buf = GdkPixbuf.Pixbuf.new(colorspace=GdkPixbuf.Colorspace.RGB,
                                       has_alpha=has_alpha,
                                       bits_per_sample=bits_per_sample,
                                       width=new_width, height=new_height)

    l_source_pixbuf.copy_area( 0, 0, l_source_pixbuf_width,
                                     l_source_pixbuf_height,
                                     new_pix_buf, 0, 0 )

    r_source_pixbuf.copy_area( 0, 0, r_source_pixbuf_width,
                                     r_source_pixbuf_height,
                                     new_pix_buf, l_source_pixbuf_width, 0 )

    return new_pix_buf

def is_image_file(path):
    """Return True if the file at <path> is an image file recognized by PyGTK.
    """
    return _SUPPORTED_IMAGE_REGEX.search(path) is not None

def convert_rgb16list_to_rgba8int(c):
    return 0x000000FF | (c[0] >> 8 << 24) | (c[1] >> 8 << 16) | (c[2] >> 8 << 8)

def rgb_to_y_601(color):
    return color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114

def text_color_for_background_color(bgcolor):
    return GTK_GDK_COLOR_BLACK if rgb_to_y_601(bgcolor) >= \
        65535.0 / 2.0 else GTK_GDK_COLOR_WHITE

def color_to_floats_rgba(color, alpha=1.0):
    return [c / 65535.0 for c in color[:3]] + [alpha]

def get_image_info(path):
    """Return information about and select preferred providers for loading
    the image specified by C{path}. The result is a tuple
    C{(format, (width, height), providers)}.
    """
    image_format = None
    image_dimensions = None
    providers = ()
    try:
        gdk_image_info = GdkPixbuf.Pixbuf.get_file_info(path)
    except Exception:
        gdk_image_info = None

    if gdk_image_info is not None and gdk_image_info[0] is not None:
        image_format = gdk_image_info[0].get_name().upper()
        image_dimensions = gdk_image_info[1], gdk_image_info[2]
        # Prefer loading via GDK/Pixbuf if Gdk.pixbuf_get_file_info appears
        # to be able to handle this path.
        providers = (constants.IMAGEIO_GDKPIXBUF, constants.IMAGEIO_PIL)
    else:
        try:
            im = Image.open(path)
            image_format = im.format
            image_dimensions = im.size
            providers = (constants.IMAGEIO_PIL, constants.IMAGEIO_GDKPIXBUF)
        except IOError:
            # If the file cannot be found, or the image
            # cannot be opened and identified.
            pass
    if image_format is None:
        image_format = _('Unknown filetype')
        image_dimensions = (0, 0)
    return (image_format, image_dimensions, providers)

def get_supported_formats():
    global _SUPPORTED_IMAGE_FORMATS
    if _SUPPORTED_IMAGE_FORMATS is None:

        # Step 1: Collect PIL formats
        # Make sure all supported formats are registered.
        Image.init()
        # Not all PIL formats register a mime type,
        # fill in the blanks ourselves.
        supported_formats_pil = {
            'BMP': (['image/bmp', 'image/x-bmp', 'image/x-MS-bmp'], []),
            'ICO': (['image/x-icon', 'image/x-ico', 'image/x-win-bitmap'], []),
            'PCX': (['image/x-pcx'], []),
            'PPM': (['image/x-portable-pixmap'], []),
            'TGA': (['image/x-tga'], []),
        }
        for name, mime in list(Image.MIME.items()):
            mime_types, extensions = supported_formats_pil.get(name, ([], []))
            supported_formats_pil[name] = mime_types + [mime], extensions
        for ext, name in list(Image.EXTENSION.items()):
            assert '.' == ext[0]
            mime_types, extensions = supported_formats_pil.get(name, ([], []))
            supported_formats_pil[name] = mime_types, extensions + [ext[1:]]
        # Remove formats with no mime type or extension.
        for name in list(supported_formats_pil.keys()):
            mime_types, extensions = supported_formats_pil[name]
            if not mime_types or not extensions:
                del supported_formats_pil[name]
        # Remove archives/videos formats.
        for name in (
            'MPEG',
            'PDF',
            'PS',
            'PSD'
        ):
            if name in supported_formats_pil:
                del supported_formats_pil[name]

        # Step 2: Collect GDK Pixbuf formats
        supported_formats_gdk = {}
        for format in GdkPixbuf.Pixbuf.get_formats():
            name = format.get_name().upper()
            assert name not in supported_formats_gdk
            supported_formats_gdk[name] = (
                format.get_mime_types(),
                format.get_extensions(),
            )

        # Step 3: merge format collections
        supported_formats = {}
        for provider in (supported_formats_gdk, supported_formats_pil):
            for name in list(provider.keys()):
                mime_types, extentions = provider[name]
                new_name = name.upper()
                new_mime_types, new_extensions = supported_formats.get( \
                    new_name, (set(), set()))
                new_mime_types.update([x.lower() for x in mime_types])
                new_extensions.update([x.lower() for x in extentions])
                supported_formats[new_name] = (new_mime_types, new_extensions)

        _SUPPORTED_IMAGE_FORMATS = supported_formats
    return _SUPPORTED_IMAGE_FORMATS

_SUPPORTED_IMAGE_FORMATS = None
# Set supported image extensions regexp from list of supported formats.
# Only used internally.
_SUPPORTED_IMAGE_REGEX = tools.formats_to_regex(get_supported_formats())
log.debug("_SUPPORTED_IMAGE_REGEX='%s'", _SUPPORTED_IMAGE_REGEX.pattern)

# vim: expandtab:sw=4:ts=4
