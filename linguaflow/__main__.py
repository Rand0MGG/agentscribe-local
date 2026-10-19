from .update_recovery import startup


def run():
    from . import diagnostic_log as diag
    diag.start_logging('desktop')
    diag.install_exception_hooks()
    startup()
    from .app import main
    main()


run()
