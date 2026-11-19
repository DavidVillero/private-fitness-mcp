plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "local.fitness.bridge"
    compileSdk = 36
    defaultConfig { applicationId = "local.fitness.bridge"; minSdk = 34; targetSdk = 35; versionCode = 8; versionName = "0.6.2" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.0")
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("androidx.work:work-runtime-ktx:2.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260719")
}

dependencyLocking { lockAllConfigurations() }

// Apply the patched Guava to app and Android test-tool configurations.
configurations.configureEach {
    resolutionStrategy.eachDependency {
        if (requested.group == "io.netty" && requested.version?.startsWith("4.1.") == true) {
            useVersion("4.1.137.Final")
            because("Patched HTTP codec and TLS handling in Android build/test tooling")
        }
        if (requested.group == "com.google.protobuf") {
            useVersion("3.25.8")
            because("Patched parser limits; keep the 3.x ABI used by Android tooling")
        }
    }
    resolutionStrategy.force("com.google.guava:guava:33.7.2-android", "com.google.guava:failureaccess:1.0.3")
}
