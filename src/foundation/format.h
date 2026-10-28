/* printf-format annotations for wrappers around the platform's vsnprintf. */
#ifndef CBM_FORMAT_H
#define CBM_FORMAT_H

#if defined(__GNUC__) || defined(__clang__)
#if defined(__MINGW32__)
/* stdio.h selects the CRT's dialect (including UCRT/C99) and handles
 * GCC vs Clang. Plain printf on MinGW GCC instead checks legacy MSVCRT. */
#include <stdio.h>
#define CBM_PRINTF_FORMAT(fmt_index, arg_index) \
    __attribute__((__format__(__MINGW_PRINTF_FORMAT, fmt_index, arg_index)))
#else
#define CBM_PRINTF_FORMAT(fmt_index, arg_index) \
    __attribute__((__format__(printf, fmt_index, arg_index)))
#endif
#else
#define CBM_PRINTF_FORMAT(fmt_index, arg_index)
#endif

#endif /* CBM_FORMAT_H */
