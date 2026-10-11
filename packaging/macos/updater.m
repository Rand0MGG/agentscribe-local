// Minimal Sparkle protocol boundary. Qt owns all presentation and recording rules.
#import <Cocoa/Cocoa.h>
#import <Sparkle/Sparkle.h>

typedef void (*ASNotification)(const char *);

@interface ASUpdateDriver : NSObject <SPUUserDriver, SPUUpdaterDelegate>
@property(nonatomic, strong) SPUUpdater *updater;
@property(nonatomic, assign) ASNotification notification;
@property(nonatomic, copy) void (^cancel)(void);
@property(nonatomic, copy) void (^choice)(SPUUserUpdateChoice);
@property(nonatomic, copy) void (^relaunch)(void);
@property(nonatomic) BOOL readyToInstall;
@property(nonatomic) BOOL allowInstall;
@property(nonatomic) uint64_t expected;
@property(nonatomic) uint64_t received;
@end

@implementation ASUpdateDriver
- (void)send:(NSString *)stage text:(NSString *)text extra:(NSDictionary *)extra {
    if (!self.notification) return;
    NSMutableDictionary *event = [@{@"stage": stage, @"text": text} mutableCopy];
    if (extra) [event addEntriesFromDictionary:extra];
    NSData *data = [NSJSONSerialization dataWithJSONObject:event options:0 error:NULL];
    self.notification([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
}
- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest *)request
                             reply:(void (^)(SUUpdatePermissionResponse *))reply {
    reply([[SUUpdatePermissionResponse alloc] initWithAutomaticUpdateChecks:NO sendSystemProfile:NO]);
}
- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation {
    self.cancel = cancellation;
    [self send:@"checking" text:@"正在检查更新" extra:nil];
}
- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem *)item state:(SPUUserUpdateState *)state
                               reply:(void (^)(SPUUserUpdateChoice))reply {
    self.choice = reply;
    self.readyToInstall = state.stage == SPUUserUpdateStageInstalling;
    [self send:item.isInformationOnlyUpdate ? @"informational" : self.readyToInstall ? @"ready" : @"available"
          text:[@"发现新版本 " stringByAppendingString:item.displayVersionString]
         extra:@{@"notes": item.itemDescription ?: @"", @"version": item.displayVersionString}];
}
- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData *)data {}
- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError *)error {}
- (void)showUpdateNotFoundWithError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    // A newer release requiring another OS must not be labelled "latest".
    NSNumber *reason = error.userInfo[SPUNoUpdateFoundReasonKey];
    BOOL latest = reason && (reason.integerValue == SPUNoUpdateFoundReasonOnLatestVersion ||
                             reason.integerValue == SPUNoUpdateFoundReasonOnNewerThanLatestVersion);
    NSString *version = [NSBundle.mainBundle objectForInfoDictionaryKey:@"AgentScribeVersion"] ?: @"";
    [self send:@"latest" text:latest ? [NSString stringWithFormat:@"当前已是最新版本（%@）。", version] : @"当前没有可安装的新版本。"
         extra:@{@"details": error.localizedDescription ?: @""}];
    acknowledgement();
}
- (void)showUpdaterError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    [self send:@"error" text:@"更新失败，当前版本与用户数据保留。"
         extra:@{@"details": error.localizedDescription ?: @""}];
    acknowledgement();
}
- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation {
    self.cancel = cancellation;
    self.expected = 0;
    self.received = 0;
    [self send:@"downloading" text:@"正在下载更新" extra:nil];
}
- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)length { self.expected = length; }
- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {
    self.received += length;
    [self send:@"downloading" text:@"正在下载更新"
         extra:self.expected ? @{@"progress": @(MIN(100., 100.*self.received/self.expected))} : nil];
}
- (void)showDownloadDidStartExtractingUpdate {
    self.cancel = nil;
    [self send:@"verifying" text:@"正在校验并准备更新" extra:nil];
}
- (void)showExtractionReceivedProgress:(double)progress {
    [self send:@"verifying" text:@"正在校验并准备更新" extra:@{@"progress": @(progress*100)}];
}
- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply {
    self.choice = reply;
    self.readyToInstall = YES;
    [self send:@"ready" text:@"更新已准备好，可重启安装。" extra:nil];
}
- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)terminated
                         retryTerminatingApplication:(void (^)(void))retry {
    [self send:@"installing" text:@"正在安装更新" extra:nil];
}
- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched acknowledgement:(void (^)(void))acknowledgement {
    [self send:@"installed" text:@"更新安装完成。" extra:nil];
    acknowledgement();
}
- (void)dismissUpdateInstallation {
    self.cancel = nil;
    self.choice = nil;
    self.relaunch = nil;
    [self send:@"dismissed" text:@"" extra:nil];
}
- (BOOL)updater:(SPUUpdater *)updater shouldPostponeRelaunchForUpdate:(SUAppcastItem *)item
 untilInvokingBlock:(void (^)(void))handler {
    if (self.allowInstall) return NO;
    self.relaunch = handler;
    [self send:@"waiting" text:@"录音与文件保存完成后可重启更新。" extra:nil];
    return YES;
}
- (BOOL)updater:(SPUUpdater *)updater shouldDownloadReleaseNotesForUpdate:(SUAppcastItem *)item { return NO; }
- (NSArray *)allowedSystemProfileKeysForUpdater:(SPUUpdater *)updater { return @[]; }
@end

static ASUpdateDriver *driver;

int ASUpdaterStart(ASNotification notification) {
    NSBundle *bundle = NSBundle.mainBundle;
    if (![bundle objectForInfoDictionaryKey:@"SUPublicEDKey"] ||
        ![bundle objectForInfoDictionaryKey:@"SUFeedURL"]) return 0;
    driver = [ASUpdateDriver new];
    driver.notification = notification;
    driver.updater = [[SPUUpdater alloc] initWithHostBundle:bundle applicationBundle:bundle
                                              userDriver:driver delegate:driver];
    driver.updater.automaticallyChecksForUpdates = NO;
    driver.updater.automaticallyDownloadsUpdates = NO;
    driver.updater.sendsSystemProfile = NO;
    NSError *error = nil;
    BOOL success = [driver.updater startUpdater:&error];
    if (!success) [driver send:@"error" text:@"原生更新器启动失败。"
                        extra:@{@"details": error.localizedDescription ?: @""}];
    return success ? 1 : 0;
}

void ASUpdaterCheck(int manual) {
    if (!driver.updater.sessionInProgress) driver.allowInstall = NO;
    if (manual) [driver.updater checkForUpdates];
    else [driver.updater checkForUpdatesInBackground];
}

void ASUpdaterChoose(int action) {
    if (!action) {
        if (driver.cancel) driver.cancel();
        else if (driver.choice) driver.choice(driver.readyToInstall ? SPUUserUpdateChoiceSkip : SPUUserUpdateChoiceDismiss);
        driver.cancel = nil;
        driver.choice = nil;
        return;
    }
    // Qt grants installation only after recording/save/process ownership ends.
    if (action == 2) {
        driver.allowInstall = YES;
        if (driver.relaunch) { driver.relaunch(); driver.relaunch = nil; return; }
    }
    if (driver.choice && (!driver.readyToInstall || driver.allowInstall)) {
        void (^reply)(SPUUserUpdateChoice) = driver.choice;
        driver.choice = nil;
        reply(SPUUserUpdateChoiceInstall);
    }
}

void ASUpdaterStop(void) {
    ASUpdaterChoose(0);
    driver.notification = NULL;
}
