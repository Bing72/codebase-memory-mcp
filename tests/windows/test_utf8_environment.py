"""Exercise UTF-8 CRT and UTF-16 Windows environment synchronization.

Run: python tests/windows/test_utf8_environment.py
Uses only a newly compiled fixture and its own synthetic environment key.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include "foundation/compat.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    const char *key = "CBM_UTF8_ENVIRONMENT_GUARD_ONLY";
    const wchar_t *wide_key = L"CBM_UTF8_ENVIRONMENT_GUARD_ONLY";
    const char *values[] = {
        "C:/ascii/cache", "C:/\uD55C\uAE00/cache", "C:/\u03A9\u03AD/cache",
        "C:/\u6D4B\u8BD5/cache", "C:/\U0001F512/cache"
    };
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
        int status = cbm_setenv(key, values[i], 1);
        if (status != 0) {
            fprintf(stderr, "cbm_setenv case %u failed with status %d (ACP=%u)\n", i, status, GetACP());
            return 1;
        }
        const char *narrow = getenv(key);
        wchar_t expected[512], actual[512];
        if (!narrow || strcmp(narrow, values[i]) != 0 ||
            !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, values[i], -1, expected, 512) ||
            !GetEnvironmentVariableW(wide_key, actual, 512) || wcscmp(expected, actual) != 0) {
            fprintf(stderr, "environment readback mismatch in case %u\n", i);
            return 2;
        }
    }
    if (cbm_setenv(key, "\xff", 1) == 0 || strcmp(getenv(key), values[4]) != 0) {
        fputs("invalid UTF-8 was accepted or changed the previous value\n", stderr);
        return 3;
    }
    puts("PASS: ASCII/Korean/Greek/CJK/emoji environment readback; invalid UTF-8 rejected");
    return 0;
}
'''


@unittest.skipUnless(os.name == 'nt', 'native Windows environment regression')
class Utf8EnvironmentTest(unittest.TestCase):
    def test_utf8_values_match_crt_and_windows_and_invalid_bytes_fail_closed(self):
        gcc = shutil.which('gcc')
        self.assertIsNotNone(gcc, 'native GCC is required')
        assert gcc is not None
        with tempfile.TemporaryDirectory(prefix='cbm-utf8-environment-') as tmp:
            root = Path(tmp)
            source, executable = root/'check.c', root/'check.exe'
            source.write_text(SOURCE, encoding='utf-8')
            compiled = subprocess.run([gcc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                       '-I', str(ROOT/'src'), str(source), '-o', str(executable)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('invalid UTF-8 rejected', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
