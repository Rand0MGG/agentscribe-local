from .update_recovery import startup


def run():
    startup()
    from .app import main
    main()


run()
