"""tools.py - Contains various helper functions."""

import os
import sys
import re
import gc
import bisect
import operator
import math
import itertools
from functools import reduce, cmp_to_key

ROOTPATH=os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_PORTABLE_MODE=[]
_NOGUI=[]
NUMERIC_REGEXP = re.compile(r"\d+|\D+")  # Split into numerics and characters
PREFIXED_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")


def cmp(a, b):
    """ Forward port of Python2's cmp function """
    return (a > b) - (a < b)

def alphanumeric_sort(filenames):
    """Do an in-place alphanumeric sort of the strings in <filenames>,
    such that for an example "1.jpg", "2.jpg", "10.jpg" is a sorted
    ordering.
    """

    filenames.sort(key=cmp_to_key(alphanumeric_compare))

def alphanumeric_compare(s1, s2):
    """ Compares two strings by their natural order (i.e. 1 before 10)
    and returns a result comparable to the cmp function.
    @return: 0 if identical, -1 if s1 < s2, +1 if s1 > s2. """
    if s1 is None:
        return 1
    elif s2 is None:
        return -1

    stringparts1 = NUMERIC_REGEXP.findall(s1.lower())
    stringparts2 = NUMERIC_REGEXP.findall(s2.lower())
    for i, part in enumerate(stringparts1):
        if part.isdigit():
            stringparts1[i] = int(part)
    for i, part in enumerate(stringparts2):
        if part.isdigit():
            stringparts2[i] = int(part)

    min_length = min(len(stringparts1), len(stringparts2))
    for i in range(min_length):
        if type(stringparts1[i]) is not type(stringparts2[i]):
            stringparts1[i] = str(stringparts1[i])
            stringparts2[i] = str(stringparts2[i])

    return cmp(stringparts1, stringparts2)

def bin_search(lst, value):
    """ Binary search for sorted list C{lst}, looking for C{value}.
    @return: List index on success. On failure, it returns the 1's
    complement of the index where C{value} would be inserted.
    This implies that the return value is non-negative if and only if
    C{value} is contained in C{lst}. """

    index = bisect.bisect_left(lst, value)
    if index != len(lst) and lst[index] == value:
        return index
    else:
        return ~index


def get_home_directory():
    """On UNIX-like systems, this method will return the path of the home
    directory, e.g. /home/username. On Windows, it will return an MComix
    sub-directory of <Documents and Settings/Username>.
    """
    if sys.platform == 'win32':
        return os.path.join(os.path.expanduser('~'), 'MComix')
    else:
        return os.path.expanduser('~')


def get_config_directory():
    """Return the path to the MComix config directory. On UNIX, this will
    be $XDG_CONFIG_HOME/mcomix, on Windows it will be the same directory as
    get_home_directory().

    See http://standards.freedesktop.org/basedir-spec/latest/ for more
    information on the $XDG_CONFIG_HOME environmental variable.
    """
    if sys.platform == 'win32':
        return get_home_directory()
    else:
        base_path = os.getenv('XDG_CONFIG_HOME',
            os.path.join(get_home_directory(), '.config'))
        return os.path.join(base_path, os.getenv('MCOMIX_PROFILE_NAME', 'mcomix'))


def get_data_directory():
    """Return the path to the MComix data directory. On UNIX, this will
    be $XDG_DATA_HOME/mcomix, on Windows it will be the same directory as
    get_home_directory().

    See http://standards.freedesktop.org/basedir-spec/latest/ for more
    information on the $XDG_DATA_HOME environmental variable.
    """
    if sys.platform == 'win32':
        return get_home_directory()
    else:
        base_path = os.getenv('XDG_DATA_HOME',
            os.path.join(get_home_directory(), '.local/share'))
        return os.path.join(base_path, 'mcomix')


def number_of_digits(n):
    if 0 == n:
        return 1
    return int(math.log10(abs(n))) + 1

def decompose_byte_size_exponent(n):
    e = 0
    while n > 1024.0:
        n /= 1024.0
        e += 1
    return (n, e)

def byte_size_exponent_to_prefix(e):
    return PREFIXED_BYTE_UNITS[min(e, len(PREFIXED_BYTE_UNITS)-1)]

def format_byte_size(n):
    nn, e = decompose_byte_size_exponent(n)
    return ('%d %s' if nn == int(nn) else '%.1f %s') % \
        (nn, byte_size_exponent_to_prefix(e))

def garbage_collect():
    """ Runs the garbage collector. """
    if sys.version_info[:3] >= (2, 5, 0):
        gc.collect(0)
    else:
        gc.collect()

def rootdir():
    # return path contains mcomixstarter.py
    return ROOTPATH

def is_portable_mode():
    # check if running in portable mode
    if not _PORTABLE_MODE:
        portable_file=os.path.join(rootdir(),'portable.txt')
        _PORTABLE_MODE.append(os.path.exists(portable_file))
        if _PORTABLE_MODE[0]:
            # chdir to rootdir early
            os.chdir(rootdir())
    return _PORTABLE_MODE[0]

def relpath2root(path,abs_fallback=False):
    # return relative path to rootdir in portable mode
    # if path is not under the same mount point where rootdir placed
    # return abspath of path if abs_fallback is True, else None
    # but, always return absolue path if not in portable mode

    # ATTENTION:
    # avoid using os.path.relpath without checking mount point in win32
    # it will raise ValueError if path has a different driver letter
    # (see source code of ntpath.relpath)

    path=os.path.abspath(path)
    if not is_portable_mode():
        return path

    pathmp=os.path.dirname(path)
    while not os.path.ismount(pathmp):
        pathmp=os.path.dirname(pathmp)

    rootmp=rootdir()
    while not os.path.ismount(rootmp):
        rootmp=os.path.dirname(rootmp)

    if pathmp==rootmp:
        return os.path.relpath(path)
    return path if abs_fallback else None

def div(a, b):
    return float(a) / float(b)

def volume(t):
    return reduce(operator.mul, t, 1)

def relerr(approx, ideal):
    return abs(div(approx - ideal, ideal))

def smaller(a, b):
    """ Returns a list with the i-th element set to True if and only if the i-th
    element in a is less than the i-th element in b. """
    return list(map(operator.lt, a, b))

def smaller_or_equal(a, b):
    """ Returns a list with the i-th element set to True if and only if the i-th
    element in a is less than or equal to the i-th element in b. """
    return list(map(operator.le, a, b))

def scale(t, factor):
    return [x * factor for x in t]

def vector_sub(a, b):
    """ Subtracts vector b from vector a. """
    return list(map(operator.sub, a, b))

def vector_add(a, b):
    """ Adds vector a to vector b. """
    return list(map(operator.add, a, b))

def vector_opposite(a):
    """ Returns the opposite vector -a. """
    return list(map(operator.neg, a))

def fixed_strings_regex(strings):
    # introduces a matching group
    strings = set(strings)
    return r'(%s)' % '|'.join(sorted([re.escape(s) for s in strings]))

def formats_to_regex(formats):
    """ Returns a compiled regular expression that can be used to search for
    file extensions specified in C{formats}. """
    return re.compile(r'\.' + fixed_strings_regex( \
        itertools.chain.from_iterable([e[1] for e in formats.values()])) \
        + r'$', re.I)

def append_number_to_filename(filename, number):
    """ Generate a new string from filename with an appended number right
    before the extension. """
    file_no_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1]
    return file_no_ext + (" (%s)" % (number)) + ext

# vim: expandtab:sw=4:ts=4
