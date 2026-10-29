"""Cocoa event delivery for the existing Sparkle bridge, without a Qt GUI host."""


def cocoa_pump():
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSEventMaskAny
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app.finishLaunching()
    loop = NSRunLoop.currentRunLoop()

    def pump():
        # Native callbacks enter the same owner thread as backend events.
        now = NSDate.dateWithTimeIntervalSinceNow_(0)
        loop.runMode_beforeDate_(NSDefaultRunLoopMode, now)
        for _ in range(64):
            event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(NSEventMaskAny, now, NSDefaultRunLoopMode, True)
            if event is None:
                break
            app.sendEvent_(event)
        app.updateWindows()
    return pump
