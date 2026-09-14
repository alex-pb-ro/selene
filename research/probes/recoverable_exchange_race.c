/* Inject one competing write immediately before the native exchange syscall.
 * This is a synthetic fault probe, not a production library.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __APPLE__
#define RENAME_FUNCTION renameatx_np
#else
#define RENAME_FUNCTION renameat2
#endif

int RENAME_FUNCTION(int from_fd, const char *from, int to_fd, const char *to, unsigned int flags) {
    typedef int (*rename_fn)(int, const char *, int, const char *, unsigned int);
#ifdef __APPLE__
    rename_fn original = (rename_fn)dlsym(RTLD_NEXT, "renameatx_np");
#else
    rename_fn original = (rename_fn)dlsym(RTLD_NEXT, "renameat2");
#endif
    if (flags == 2 && strcmp(from, "first.py") == 0 && getenv("SELENE_INJECT_EXCHANGE_RACE")) {
        unsetenv("SELENE_INJECT_EXCHANGE_RACE");
        int target = openat(from_fd, from, O_WRONLY | O_TRUNC | O_NOFOLLOW);
        const char competing[] = "concurrent_edit = 99\n";
        if (target < 0 || write(target, competing, sizeof(competing) - 1) != sizeof(competing) - 1 || fsync(target) != 0) {
            _exit(74);
        }
        close(target);
    }
    if (!original) _exit(75);
    return original(from_fd, from, to_fd, to, flags);
}
