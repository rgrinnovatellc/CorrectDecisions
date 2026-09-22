plugins {
    id("com.android.application")
}

android {
    namespace = "org.lostboundaries.probe"
    compileSdk = 37

    defaultConfig {
        applicationId = "org.lostboundaries.probe"
        minSdk = 37
        targetSdk = 37
        versionCode = 1
        versionName = "1"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
