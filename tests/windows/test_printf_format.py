"""Compile the real printf-wrapper declarations with GCC or Clang.

Run: CC=gcc python tests/windows/test_printf_format.py
No product binary, linker, third-party dependencies, or network is needed.
"""

import os
from pathlib import Path
import shlex
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = (
    ("foundation/arena.h", "(void)cbm_arena_sprintf(NULL, {args});"),
    ("ui/httpd.h", 'cbm_http_replyf(NULL, 200, "", {args});'),
)


class PrintfFormatTest(unittest.TestCase):
    def compile(self, header, call, args, stdio_first=False):
        # Test the product header before stdio too: the annotation must not
        # depend on the caller's include order to select MinGW's CRT dialect.
        prefix = "#include <stdio.h>\n" if stdio_first else ""
        source = (
            prefix
            + '#include "' + header + '"\n'
            + "void check(void) { " + call.format(args=args) + " }\n"
        )
        command = shlex.split(os.environ.get("CC", "gcc")) + [
            "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wformat=2",
            "-I", str(ROOT / "src"), "-x", "c", "-fsyntax-only", "-",
        ]
        result = subprocess.run(
            command, input=source, text=True, capture_output=True, timeout=30,
            env={**os.environ, "LC_ALL": "C"},
        )
        diagnostic = (
            "command: " + subprocess.list2cmdline(command)
            + "\nsource:\n" + source + "\n" + result.stdout + result.stderr
        )
        return result, diagnostic

    def test_c99_size_and_long_long_formats(self):
        for header, call in WRAPPERS:
            for stdio_first in (False, True):
                with self.subTest(header=header, stdio_first=stdio_first):
                    result, diagnostic = self.compile(
                        header, call, '"%zu %lld", (size_t)42, -1234567890123LL',
                        stdio_first,
                    )
                    self.assertEqual(result.returncode, 0, diagnostic)
                    self.assertEqual(result.stderr, "", diagnostic)

    def test_incorrect_format_arguments_are_rejected(self):
        for header, call in WRAPPERS:
            for args in (
                '"%d", "not an int"',
                '"%zu", "not a size_t"',
                '"%lld", "not a long long"',
                '"%d"',
            ):
                with self.subTest(header=header, args=args):
                    result, diagnostic = self.compile(header, call, args)
                    self.assertNotEqual(result.returncode, 0, diagnostic)
                    self.assertIn("-Werror=format", result.stderr, diagnostic)


if __name__ == "__main__":
    unittest.main(verbosity=2)
