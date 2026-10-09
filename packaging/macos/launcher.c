/* Keep the main process inside the application bundle for Cocoa/TCC identity.
 * Workers use the separate, complete portable interpreter, never this launcher.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <CoreFoundation/CoreFoundation.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], resources[PATH_MAX], python[PATH_MAX];
    uint32_t size = sizeof executable;
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, resolved)) return 1;
    char *slash = strrchr(resolved, '/');
    if (!slash) return 1;
    *slash = '\0';
    if (snprintf(resources, sizeof resources, "%s/../Resources", resolved) >= (int)sizeof resources
        || !realpath(resources, executable)) return 1;
    strcpy(resources, executable);
    if (snprintf(python, sizeof python, "%s/python", resources) >= (int)sizeof python) return 1;
    setenv("AGENTSCRIBE_PACKAGED", "1", 1);
    setenv("AGENTSCRIBE_RESOURCES", resources, 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    unsetenv("PYTHONHOME");  /* Do not leak an embedding prefix into worker venvs. */
    if (!getenv("SSL_CERT_FILE")) {
        char certificates[PATH_MAX];
        if (snprintf(certificates, sizeof certificates, "%s/lib/python3.12/site-packages/certifi/cacert.pem", python)
            >= (int)sizeof certificates) return 1;
        setenv("SSL_CERT_FILE", certificates, 1);
    }
    const char *inherited = getenv("PYTHONPATH");
    size_t length = strlen(resources) + (inherited ? strlen(inherited) : 0) + 2;
    char *path = malloc(length);
    if (!path) return 1;
    snprintf(path, length, "%s%s%s", resources, inherited ? ":" : "", inherited ? inherited : "");
    setenv("PYTHONPATH", path, 1);
    free(path);

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.user_site_directory = 0;
    config.write_bytecode = 0;
    PyStatus status = PyConfig_SetBytesString(&config, &config.home, python);
    if (PyStatus_Exception(status)) goto failed;
    char interpreter[PATH_MAX];
    if (snprintf(interpreter, sizeof interpreter, "%s/bin/python3", python) >= (int)sizeof interpreter) return 1;
    status = PyConfig_SetBytesString(&config, &config.executable, interpreter);
    if (PyStatus_Exception(status)) goto failed;
    /* This diagnostic entry also verifies the real native launcher without
     * starting recording, a model preparation, or an ordinary app session. */
    if (argc > 1 && strcmp(argv[1], "--python") == 0) {
        argv[1] = interpreter;
        status = PyConfig_SetBytesArgv(&config, argc - 1, argv + 1);
    } else {
        char **arguments = calloc((size_t)argc + 3, sizeof(char *));
        if (!arguments) return 1;
        arguments[0] = interpreter;
        arguments[1] = "-m";
        arguments[2] = "linguaflow";
        for (int i = 1; i < argc; ++i) arguments[i + 2] = argv[i];
        status = PyConfig_SetBytesArgv(&config, argc + 2, arguments);
        free(arguments);
    }
    if (PyStatus_Exception(status)) goto failed;
    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) goto failed;
    PyConfig_Clear(&config);
    return Py_RunMain();
failed:
    PyConfig_Clear(&config);
    Py_ExitStatusException(status);
}
