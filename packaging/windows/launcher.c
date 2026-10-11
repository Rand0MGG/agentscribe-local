/* Embed the locked CPython in the GUI process. Workers use python/python.exe. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    (void)instance; (void)previous; (void)command; (void)show;
    wchar_t resources[32768], python[32768], path[32768], interpreter[32768];
    DWORD size = GetModuleFileNameW(NULL, resources, 32768);
    if (!size || size >= 32768) return 1;
    wchar_t *slash = wcsrchr(resources, L'\\');
    if (!slash) return 1;
    *slash = L'\0';
    if (_snwprintf_s(python, 32768, _TRUNCATE, L"%s\\python", resources) < 0 ||
        _snwprintf_s(interpreter, 32768, _TRUNCATE, L"%s\\python.exe", python) < 0) return 1;
    _wputenv_s(L"AGENTSCRIBE_PACKAGED", L"1");
    _wputenv_s(L"AGENTSCRIBE_RESOURCES", resources);
    _wputenv_s(L"PYTHONNOUSERSITE", L"1");
    _wputenv_s(L"PYTHONDONTWRITEBYTECODE", L"1");
    _wputenv_s(L"PYTHONHOME", L"");
    /* Normal launcher never adds a developer checkout or user site. */
    _wputenv_s(L"PYTHONPATH", resources);
    if (_snwprintf_s(path, 32768, _TRUNCATE, L"%s\\Lib\\site-packages\\certifi\\cacert.pem", python) < 0) return 1;
    _wputenv_s(L"SSL_CERT_FILE", path);
    int count;
    wchar_t **arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!arguments) return 1;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.user_site_directory = 0;
    config.safe_path = 1;
    config.write_bytecode = 0;
    PyStatus status = PyConfig_SetString(&config, &config.home, python);
    if (PyStatus_Exception(status)) goto failed;
    status = PyConfig_SetString(&config, &config.executable, interpreter);
    if (PyStatus_Exception(status)) goto failed;
    if (count > 1 && wcscmp(arguments[1], L"--python") == 0) {
        arguments[1] = interpreter;
        status = PyConfig_SetArgv(&config, count - 1, arguments + 1);
    } else {
        wchar_t **argv = calloc((size_t)count + 3, sizeof(wchar_t *));
        if (!argv) goto failed;
        argv[0] = interpreter; argv[1] = L"-m"; argv[2] = L"linguaflow";
        for (int i = 1; i < count; ++i) argv[i + 2] = arguments[i];
        status = PyConfig_SetArgv(&config, count + 2, argv);
        free(argv);
    }
    if (PyStatus_Exception(status)) goto failed;
    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) goto failed;
    PyConfig_Clear(&config);
    LocalFree(arguments);
    return Py_RunMain();
failed:
    MessageBoxW(NULL, L"应用启动组件不可用。请重新安装完整的 AgentScribe；已有录音与模型会保留。",
                L"AgentScribe", MB_OK | MB_ICONERROR);
    PyConfig_Clear(&config);
    LocalFree(arguments);
    return 1;
}
