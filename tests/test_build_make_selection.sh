#!/usr/bin/env bash
# Exercise the build entry's tool selection without installing a toolchain.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cbm-make-selection.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

cat > "$WORK/mingw32-make" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == --version ]]; then
    printf 'GNU Make fixture\n'
else
    printf '%s\n' "$@" > "$CBM_MAKE_TRACE"
fi
STUB
chmod +x "$WORK/mingw32-make"
export CBM_MAKE_TRACE="$WORK/arguments"

# A host may have GNU make already. Intercept executable discovery, not the
# selection logic, so this also proves the Windows fallback on Linux/macOS.
command() {
    if [[ "${1:-}" == -v ]]; then
        case "${2:-}" in
            make|gmake) return 1 ;;
            mingw32-make) printf '%s\n' "$WORK/mingw32-make"; return 0 ;;
        esac
    fi
    builtin command "$@"
}

unset MAKE CBM_BUILD_JOBS
source "$ROOT/scripts/env.sh"
cbm_configure_make
cbm_make -j2 -f Makefile.cbm cbm
if ! grep -Fx -- '-j2' "$CBM_MAKE_TRACE" >/dev/null ||
   ! grep -Fx -- 'cbm' "$CBM_MAKE_TRACE" >/dev/null; then
    echo 'FAIL: native GNU make fallback lost build arguments' >&2
    exit 1
fi
if [[ "$OS" == windows ]]; then
    expected_shell="SHELL=$(cygpath -m "$(builtin command -v sh)")"
    grep -Fx -- "$expected_shell" "$CBM_MAKE_TRACE" >/dev/null || {
        echo 'FAIL: native make did not receive the Windows shell path' >&2
        exit 1
    }
fi
printf 'PASS: build accepts GNU mingw32-make when make is absent\n'

# Non-Windows hosts leave CBM_MAKE_ARGS empty; set -u must not reject it.
OS=linux
cbm_configure_make
cbm_make -j2 -f 'Makefile with spaces.cbm' 'VALUE=two words' '' 'literal*?[x]'
printf '%s\n' -j2 -f 'Makefile with spaces.cbm' 'VALUE=two words' '' 'literal*?[x]' > "$WORK/expected"
cmp "$WORK/expected" "$CBM_MAKE_TRACE" || {
    echo 'FAIL: empty make prefix changed argument boundaries' >&2
    exit 1
}
printf 'PASS: empty make prefix preserves all arguments under set -u\n'

CBM_MAKE_ARGS=('SHELL=C:/tool chain/sh.exe' 'PREFIX=two words' '')
cbm_make -j2 'VALUE=two words' '' 'literal*?[x]'
printf '%s\n' 'SHELL=C:/tool chain/sh.exe' 'PREFIX=two words' '' \
    -j2 'VALUE=two words' '' 'literal*?[x]' > "$WORK/expected"
cmp "$WORK/expected" "$CBM_MAKE_TRACE" || {
    echo 'FAIL: populated make prefix changed argument boundaries' >&2
    exit 1
}
printf 'PASS: populated make prefix preserves all arguments under set -u\n'
