# Android, Zepp and Garmin

## Source version and build

The reviewed source was 0.6.0; the remediation candidate declares **0.6.2, versionCode 8**, application ID `local.fitness.bridge`. It includes the newer UI, upload checkpoint implementation/tests, source-preserving streams, and periodic-work reconciliation found in the newer inspected local tree. No APK, installed-device identifier, build cache, debug/release signing key, SDK or proprietary vendor app is distributed.

Build requirements from the checked-in Gradle files: JDK 17, Gradle 8.11.1, Android Gradle Plugin 8.10.1, Kotlin 2.1.20, compile SDK 36, minimum Android API 34 (Android 14), target SDK 35. Use your own SDK installation with required platform/build-tools packages and review its license terms. The open-source AndroidX dependencies are fetched through Google Maven/Maven Central.

```sh
# Dummy paths: replace with your own installations.
export JAVA_HOME=/absolute/path/to/jdk-17
export ANDROID_HOME=/absolute/path/to/android-sdk
services/private-fitness-mcp/scripts/android-build :app:testDebugUnitTest :app:assembleDebug :app:lintDebug
```

The build launcher downloads the official Gradle archive into an external cache, verifies its pinned SHA-256, and enables strict dependency checks against the checked-in verification metadata and dependency lock. Do not regenerate checksums merely to silence a failure.

The APK is generated under `services/private-fitness-mcp/android/app/build/outputs/apk/debug/`. It is ignored. Install on your own phone through Android Studio or authorized USB debugging. A newly generated debug key cannot update an existing installation signed by a different key. Do not uninstall an existing app just to bypass that error: uninstalling may erase pairing, queued records and cursors. Use your existing key privately for an upgrade, or plan a separate fresh installation.

## Connect the wearable apps

1. Pair and sync your wearable in its official Garmin Connect or Zepp app. This project does not pair directly with the watches.
2. In the vendor app, enable sharing to Android Health Connect for the desired categories. Menu names vary by app version and region. Confirm that the vendor app is permitted to **write** those categories in Android Health Connect.
3. In Health Connect, inspect whether records from the expected source actually exist. The bridge recognizes Garmin origin `com.garmin.android.apps.connectmobile` and Zepp origin `com.huami.watch.hmwatchmanager`. It does not relabel another app's records as Garmin/Zepp.
4. Open Private Fitness → Settings → Manage health permissions. Grant the bridge **read** access to the categories you want. The bridge does not request write access to Health Connect.
5. For optional automatic sync, grant background read access where supported and enable Automatic sync. Android schedules it approximately hourly; this is not a timing guarantee. The initial import covers seven days. The app no longer requests unused extended-history access. An expired change token triggers a bounded 30-day reread, but missed deletions and edits older than that window remain unverified and require manual reconciliation.

Do not infer unavailable vendor exports from an empty query. Missing values can reflect permissions, app sync, wear time, historical windows or unsupported categories. This export does not certify every Garmin/Zepp model, app version or metric.

Sources: [Garmin's Health Connect guidance](https://support.garmin.com/en-GB/?faq=JToBEy0jfe6pIygark2Ui5), [Android Health Connect reading and permissions](https://developer.android.com/health-and-fitness/health-connect/read-data), [official Zepp app listing](https://play.google.com/store/apps/details?id=com.huami.watch.hmwatchmanager). Exact current Zepp menu labels were not independently verified for this export; use the app's Health Connect integration and Android permission screens.

## Pair with the host

Complete the ingestion/private HTTPS steps in [setup](setup.md). On the phone, open Settings → Advanced pairing. Enter your own private HTTPS endpoint ending in `/v1/ingest` and the token from your locally generated `services/private-fitness-mcp/secrets/phone-token`. Transfer/enter that token privately. The example pairing JSON is illustrative and must not be used as a credential.

The app encrypts the token using Android Keystore. Cloud backup and device transfer are disabled for app data. The optional USB pairing import consumes `files/mac-pairing.json` in app-private storage; this requires an authorized local/debug workflow, not a public downloadable pairing file. Manual pairing is sufficient.

Tap Sync now. Each source stream retains its own outbox and cursor. A batch is checkpointed only after a matching server acknowledgment; the source cursor advances after its queued batches complete. After an expired token, a replacement token is reserved before re-reading up to 30 days of source records. Records are deduplicated by stable identity server-side, but events deleted while the token was expired cannot be reconstructed from a snapshot; the app retains a visible warning in sync status. Changed permission sets remain a manual reconciliation gate to prevent silent history loss. Interruptions retry from persisted progress. Completion receipts do not prove wearable completeness. Do not delete app state to clear a retry without inspecting the cause.

For troubleshooting: check the private network on both devices, host availability, HTTPS certificate, pairing token, Health Connect permissions, and upstream vendor sync. The diagnostic export button exports a real record if present; its output is private data and is excluded from Git.

## Optional direct Garmin detail cache

Health Connect and direct Garmin are separate pipelines. Direct Garmin adds recorded exercise sets, repetitions, weights, workout heart-rate detail and cached activity metadata when available. It does not fill absent daily Health Connect values or add duplicate workout calories.

This release ships the cache schema and read-only tools, not a sync adapter. An earlier private adapter used an unofficial login library and was removed. Garmin now offers a [Personal API](https://developer.garmin.com/gc-developer-program/overview) for retrieving your own data; a replacement adapter should use it and respect its terms. Until one exists, the cache stays empty and the workout tools report no cached activities.

Recorded labels may be wrong or unknown. The normalizer treats unlabelled exercise-set weights as grams; explicit units take precedence. Raw payloads are retained privately for inspection. Removed vendor activities are not automatically deleted from the cache.
