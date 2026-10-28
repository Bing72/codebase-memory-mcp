"""Build a real Windows product recipe longer than cmd.exe's argument limit.

The fixture overrides only input lists/flags in the actual Makefile. No vendored
rebuild, network, application cache, or operator daemon is used.
Run: python tests/windows/test_product_response_file.py
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def long_object_list(obj, tail_obj):
    return ' '.join([obj.as_posix()] * (10000 // len(obj.as_posix()) + 1) + [tail_obj.as_posix()])


class ProductObjectListTest(unittest.TestCase):
    def test_object_list_exceeds_limit_independent_of_path_length(self):
        for obj in (Path('e.o'), Path('C:/t/cbm-product-response-abcdefgh/empty.o'),
                    Path('C:/' + 'long-' * 40 + '/empty.o')):
            with self.subTest(obj=obj):
                tail_obj = obj.with_name('tail.o')
                objects = long_object_list(obj, tail_obj)
                self.assertGreater(len(objects), 10000)
                self.assertEqual(objects.split()[-1], tail_obj.as_posix())
                self.assertTrue(all(p == obj.as_posix() for p in objects.split()[:-1]))


@unittest.skipUnless(os.name == 'nt', 'native Windows command-line regression')
class ProductResponseFileTest(unittest.TestCase):
    def test_long_product_link_preserves_all_objects_and_quoted_version(self):
        gcc = shutil.which('gcc')
        make = next((shutil.which(n) for n in ('make', 'gmake', 'mingw32-make')
                     if shutil.which(n)), None)
        shell = shutil.which('sh')
        self.assertTrue(gcc and make and shell, 'GCC, GNU make, and Git Bash sh are required')
        assert gcc is not None and make is not None and shell is not None
        with tempfile.TemporaryDirectory(prefix='cbm-product-response-') as tmp:
            work = Path(tmp)
            source = work/'main.c'
            source.write_text('#include <stdio.h>\nint cbm_response_tail(void);\n'
                              'int main(void) { puts(CBM_VERSION); return cbm_response_tail() != 37; }\n', encoding='utf-8')
            empty = work/'empty.c'
            empty.write_text('typedef int no_exported_symbols;\n', encoding='utf-8')
            obj = work/'empty.o'
            tail = work/'tail.c'
            tail.write_text('int cbm_response_tail(void) { return 37; }\n', encoding='utf-8')
            tail_obj = work/'tail.o'
            for src, output in ((empty, obj), (tail, tail_obj)):
                compiled = subprocess.run([gcc, '-c', str(src), '-o', str(output)],
                                          capture_output=True, text=True, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
            objects = long_object_list(obj, tail_obj)
            self.assertGreater(len(objects), 10000)
            build = work/'build'
            target = build/'codebase-memory-mcp'
            # Exactly the quoting emitted by scripts/build.sh --version.
            version_flag = '-DCBM_VERSION="' + chr(92) + '"response-fixture' + chr(92) + '""'
            command = [make, '-f', 'Makefile.cbm', target.as_posix(),
                       'SHELL='+Path(shell).as_posix(), 'CC='+Path(gcc).as_posix(),
                       'BUILD_DIR='+build.as_posix(), 'SANITIZE=',
                       'MAIN_SRC='+source.as_posix(), 'PROD_SRCS=', 'EXTRACTION_SRCS=',
                       'AC_LZ4_SRCS=', 'ZSTD_SRCS=', 'SQLITE_WRITER_SRC=',
                       'PROJECT_HDRS=', 'OBJS_VENDORED_PROD='+objects, 'LDFLAGS=',
                       'CFLAGS_PROD=-std=c11 '+version_flag]
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            executable = Path(str(target)+'.exe')
            self.assertTrue(executable.is_file(), 'product recipe did not emit a real executable')
            ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(ran.stdout.strip(), 'response-fixture')


if __name__ == '__main__':
    unittest.main(verbosity=2)
