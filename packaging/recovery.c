/* Only OS primitives live here; the recovery state machine is shared Python. */
#include <stdint.h>
#ifdef _WIN32
#include <windows.h>
#define EXPORT __declspec(dllexport)
static int move_path(const char *source, const char *destination) {
    wchar_t a[32768], b[32768];
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, source, -1, a, 32768) ||
        !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, destination, -1, b, 32768)) return 0;
    return MoveFileExW(a, b, MOVEFILE_WRITE_THROUGH) != 0;
}
static uint64_t stamp_handle(HANDLE process) {
    FILETIME created, exited, kernel, user;
    uint64_t result = 0;
    DWORD status;
    if (process && GetExitCodeProcess(process, &status) && status == STILL_ACTIVE &&
        GetProcessTimes(process, &created, &exited, &kernel, &user))
        result = ((uint64_t)created.dwHighDateTime << 32) | created.dwLowDateTime;
    return result;
}
EXPORT uint64_t ASProcessStamp(unsigned long pid) {
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    uint64_t result = stamp_handle(process);
    if (process) CloseHandle(process);
    return result;
}
EXPORT int ASStopStartup(unsigned long pid, uint64_t stamp) {
    HANDLE process = OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    int result = stamp && stamp_handle(process) == stamp && TerminateProcess(process, 1);
    if (process) CloseHandle(process);
    return result;
}
#else
#include <stdio.h>
#include <signal.h>
#include <libproc.h>
#include <sys/proc_info.h>
#define EXPORT __attribute__((visibility("default")))
static int move_path(const char *source, const char *destination) {
    return rename(source, destination) == 0;
}
EXPORT uint64_t ASProcessStamp(unsigned long pid) {
    struct proc_bsdinfo info;
    /* SZOMB is 5: an exited but unreaped owned child is no longer running. */
    if (proc_pidinfo((int)pid, PROC_PIDTBSDINFO, 0, &info, sizeof info) != sizeof info || info.pbi_status == 5) return 0;
    return info.pbi_start_tvsec * 1000000ULL + info.pbi_start_tvusec;
}
EXPORT int ASStopStartup(unsigned long pid, uint64_t stamp) {
    return stamp && ASProcessStamp(pid) == stamp && kill((int)pid, SIGTERM) == 0;
}
#endif
/* The failed candidate is retained. If restoration fails, put it back; never
 * leave a half-deleted installation or touch any user data directory. */
EXPORT int ASRecoverySwap(const char *installed, const char *backup, const char *failed) {
    if (!move_path(installed, failed)) return 0;
    if (move_path(backup, installed)) return 1;
    move_path(failed, installed);
    return 0;
}
