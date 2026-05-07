from __future__ import annotations

import ezdxf
import ezdxf.tools.crypt


def _patched_decode(text_lines):
    def _safe_decode_line(text):
        try:
            b = bytes(text, "utf-8")
        except UnicodeEncodeError:
            try:
                b = bytes(text, "ascii")
            except UnicodeEncodeError:
                b = bytes(text, "latin-1", errors="replace")

        dectab = ezdxf.tools.crypt._decode_table
        s = []
        skip = False
        for c in b:
            if skip:
                skip = False
                continue
            if c in dectab:
                s += dectab[c]
                skip = (c == 0x5E)
            else:
                s += chr(c ^ 0x5F)
        return "".join(s)
    return (_safe_decode_line(line) for line in text_lines)


def apply_ezdxf_patch():
    ezdxf.tools.crypt.decode = _patched_decode